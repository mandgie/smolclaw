"""Cron scheduler — fires job triggers through the router as regular messages."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from croniter import croniter

if TYPE_CHECKING:
    from .router import Router

log = logging.getLogger("smolclaw")

__all__ = ["InvalidScheduleError", "Job", "Scheduler"]


class InvalidScheduleError(ValueError):
    """Raised when a cron schedule expression is invalid."""


class Job:
    """A scheduled job definition."""

    def __init__(self, data: dict[str, Any], prompts_base: Path | None = None):
        """Initialize a job from its JSON data dict.

        Args:
            data: Job definition with id, agent, schedule, and optional prompt/delivery fields.
            prompts_base: Directory to resolve prompt_file paths against.
        """
        self.id: str = data["id"]
        self.agent: str = data["agent"]
        self.schedule: str = data["schedule"]
        self.enabled: bool = data.get("enabled", True)

        # Validate cron expression early — fail at creation, not at runtime
        try:
            croniter(self.schedule)
        except (ValueError, KeyError, TypeError) as e:
            raise InvalidScheduleError(
                f"Job '{self.id}': invalid cron schedule '{self.schedule}': {e}"
            ) from e
        self.delivery: str = data.get("delivery", "")
        self.delivery_chat_id: str = data.get("delivery_chat_id", "")
        self.session_mode: str = data.get("session_mode", "isolated")

        # Load prompt from file or inline
        self.prompt_file: str = data.get("prompt_file", "")
        self.prompt: str = data.get("prompt", "")
        if self.prompt_file and prompts_base:
            path = prompts_base / self.prompt_file
            if path.exists():
                self.prompt = path.read_text().strip()
            else:
                log.warning(f"Job {self.id}: prompt file not found: {path}")

        # Runtime state
        self.last_run: str = data.get("last_run", "")
        self.next_run: str = data.get("next_run", "")
        self.status: str = data.get("status", "pending")
        self.failures: int = data.get("failures", 0)

    def __repr__(self) -> str:
        return f"Job(id={self.id!r}, agent={self.agent!r}, schedule={self.schedule!r})"

    def compute_next_run(self, after: datetime | None = None) -> datetime:
        """Compute the next run time from the cron expression."""
        base = after or datetime.now()
        cron = croniter(self.schedule, base)
        return cron.get_next(datetime)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the job back to a JSON-compatible dict."""
        d: dict[str, Any] = {
            "id": self.id,
            "agent": self.agent,
            "schedule": self.schedule,
            # If prompt_file is set, keep prompt empty on disk (file is source of truth)
            "prompt": "" if self.prompt_file else self.prompt,
            "enabled": self.enabled,
            "delivery": self.delivery,
            "delivery_chat_id": self.delivery_chat_id,
            "session_mode": self.session_mode,
            "last_run": self.last_run,
            "next_run": self.next_run,
            "status": self.status,
            "failures": self.failures,
        }
        if self.prompt_file:
            d["prompt_file"] = self.prompt_file
        return d


class Scheduler:
    """Cron scheduler that fires job triggers through the router."""

    def __init__(
        self,
        jobs_path: Path,
        agents_dir: Path,
        router: Router,
        deliver_callback: Callable[[Job, str], Awaitable[None]] | None = None,
    ):
        """Initialize the scheduler.

        Args:
            jobs_path: Path to the jobs.json file.
            agents_dir: Base directory containing agent folders (for prompt file resolution).
            router: The message router used to dispatch job triggers.
            deliver_callback: Optional async callback for delivering job output to channels.
        """
        self.jobs_path = jobs_path
        self.agents_dir = agents_dir
        self.router = router
        self._deliver_callback = deliver_callback
        self.jobs: list[Job] = []
        self._task: asyncio.Task | None = None
        self._running = False

    def __repr__(self) -> str:
        return f"Scheduler(jobs={len(self.jobs)}, running={self._running})"

    def load_jobs(self) -> None:
        """Load jobs from jobs.json.

        All valid jobs are loaded, including disabled ones, to avoid data loss
        when ``save_jobs()`` persists the list back to disk.
        """
        if not self.jobs_path.exists():
            self.jobs = []
            return

        try:
            data = json.loads(self.jobs_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            log.error(f"Scheduler: failed to read jobs file: {e}")
            self.jobs = []
            return

        self.jobs = []
        for job_data in data:
            try:
                prompts_base = self.agents_dir / job_data["agent"] / "prompts"
                job = Job(job_data, prompts_base=prompts_base)
            except InvalidScheduleError as e:
                log.warning(f"Scheduler: skipping job with bad schedule: {e}")
                continue
            except (KeyError, TypeError) as e:
                log.warning(f"Scheduler: skipping malformed job: {e}")
                continue

            # Compute next_run only for schedulable jobs (enabled + has prompt).
            # Disabled and promptless jobs are still kept so save_jobs() doesn't
            # silently drop them from the file.
            if job.enabled and job.prompt:
                if job.next_run:
                    try:
                        datetime.fromisoformat(job.next_run)
                    except (ValueError, TypeError):
                        log.warning(
                            f"Scheduler: job '{job.id}' has invalid next_run "
                            f"'{job.next_run}', recomputing"
                        )
                        job.next_run = job.compute_next_run().isoformat()
                else:
                    job.next_run = job.compute_next_run().isoformat()

            self.jobs.append(job)

        enabled_count = sum(1 for j in self.jobs if j.enabled and j.prompt)
        log.info(f"Scheduler: loaded {len(self.jobs)} jobs ({enabled_count} schedulable)")
        # Persist computed next_run values so CLI/disk stays in sync
        if any(j.enabled and j.prompt for j in self.jobs):
            self.save_jobs()

    def save_jobs(self) -> None:
        """Persist jobs back to jobs.json.

        Uses atomic write (write-to-temp + rename) to avoid corrupting the file
        if the process crashes mid-write.
        """
        self.jobs_path.parent.mkdir(parents=True, exist_ok=True)
        data = [j.to_dict() for j in self.jobs]
        content = json.dumps(data, indent=2)

        # Atomic write: temp file in same directory → os.replace()
        try:
            fd, tmp_path = tempfile.mkstemp(dir=str(self.jobs_path.parent), suffix=".tmp")
            try:
                os.write(fd, content.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
            Path(tmp_path).replace(self.jobs_path)
        except OSError:
            # Fallback to direct write if atomic fails (e.g. cross-device)
            self.jobs_path.write_text(content)

    async def start(self) -> None:
        """Start the scheduler loop."""
        self.load_jobs()
        self._running = True
        self._start_loop()
        log.info("Scheduler: started")

    def _start_loop(self) -> None:
        """Create the loop task with a done callback for crash detection."""
        self._task = asyncio.create_task(self._loop())
        self._task.add_done_callback(self._on_loop_done)

    def _on_loop_done(self, task: asyncio.Task) -> None:
        """Restart the loop if it crashed unexpectedly."""
        if not self._running:
            return  # Clean shutdown, nothing to do

        if task.cancelled():
            log.warning("Scheduler: loop was cancelled, restarting in 5s")
        else:
            exc = task.exception()
            if exc:
                log.error(f"Scheduler: loop crashed ({exc}), restarting in 5s")
            else:
                log.warning("Scheduler: loop exited unexpectedly, restarting in 5s")

        # Schedule restart on the event loop
        try:
            loop = asyncio.get_running_loop()
            loop.call_later(5, self._start_loop)
        except RuntimeError:
            log.error("Scheduler: no running event loop, cannot restart")

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        log.info("Scheduler: stopped")

    def _compute_sleep(self) -> float:
        """Compute optimal sleep duration until the next due job.

        Returns the number of seconds to sleep — the minimum of:
        - Time until the earliest next_run across all enabled jobs
        - MAX_SLEEP_SECONDS (60s) as a ceiling for responsiveness

        Falls back to MAX_SLEEP_SECONDS when no schedulable jobs exist
        or all next_run values are unparseable.
        """
        max_sleep = 60.0
        min_sleep = 1.0

        now = datetime.now()
        nearest = max_sleep

        for job in self.jobs:
            if not job.enabled or not job.prompt or not job.next_run:
                continue
            try:
                next_dt = datetime.fromisoformat(job.next_run)
                delta = (next_dt - now).total_seconds()
                if delta < nearest:
                    nearest = delta
            except (ValueError, TypeError):
                continue  # Bad next_run handled by the main loop

        # Clamp: at least min_sleep to avoid busy-spinning, at most max_sleep
        return max(min_sleep, min(nearest, max_sleep))

    async def _loop(self) -> None:
        """Main scheduler loop — sleeps until the next job is due."""
        import time

        from .router import InboundMessage

        while self._running:
            now = datetime.now()

            for job in self.jobs:
                if not job.enabled or not job.prompt or not job.next_run:
                    continue

                # Per-job isolation: a bad next_run string must not kill the loop
                try:
                    next_dt = datetime.fromisoformat(job.next_run)
                except (ValueError, TypeError) as e:
                    log.error(
                        f"Scheduler: job '{job.id}' has invalid next_run "
                        f"'{job.next_run}', recomputing: {e}"
                    )
                    try:
                        job.next_run = job.compute_next_run().isoformat()
                        self.save_jobs()
                    except Exception as e2:
                        log.error(
                            f"Scheduler: job '{job.id}' failed to recompute next_run, "
                            f"disabling: {e2}"
                        )
                        job.enabled = False
                        self.save_jobs()
                    continue

                if now >= next_dt:
                    log.info(f"Scheduler: firing job '{job.id}' for agent '{job.agent}'")
                    job_start = time.monotonic()
                    from .tracing import trace_cron_job

                    with trace_cron_job(job.id, job.agent):
                        try:
                            message = InboundMessage(
                                agent=job.agent,
                                text=job.prompt,
                                source="cron",
                                chat_id=job.delivery_chat_id,
                                session_key=f"cron:{job.id}",
                            )
                            outbound = await self.router.route(message)

                            # Deliver to channel if configured.
                            # Suppress delivery when the agent responds with
                            # NO_SUGGESTIONS (convention: nothing needs attention).
                            if self._is_no_suggestions(outbound.text):
                                log.info(
                                    f"Scheduler: job '{job.id}' returned "
                                    f"NO_SUGGESTIONS — skipping delivery"
                                )
                            elif job.delivery and job.delivery_chat_id:
                                await self._deliver(job, outbound.text)

                            job.last_run = now.isoformat()
                            job.status = "ok"
                            job.failures = 0
                        except asyncio.CancelledError:
                            # A cancelled job must not kill the entire scheduler.
                            # Log and continue — the loop will pick up the next job.
                            log.warning(f"Scheduler: job '{job.id}' was cancelled mid-flight")
                            job.status = "cancelled"
                        except Exception as e:
                            log.error(f"Scheduler: job '{job.id}' failed: {e}")
                            job.status = "error"
                            job.failures += 1

                    # Clean up: disconnect agent session after cron jobs to
                    # prevent stale SDK connections from accumulating and
                    # burning CPU (CLOSE_WAIT sockets, leaked file descriptors).
                    if job.session_mode == "isolated":
                        agent = self.router.get_agent(job.agent)
                        if agent:
                            try:
                                await agent.new_session()
                            except (Exception, asyncio.CancelledError) as e:
                                log.debug(
                                    f"Scheduler: session cleanup for "
                                    f"'{job.agent}' failed (ignored): {e}"
                                )

                    elapsed = time.monotonic() - job_start
                    log.info(f"Scheduler: job '{job.id}' completed in {elapsed:.1f}s")

                    # Compute next run
                    job.next_run = job.compute_next_run(after=now).isoformat()
                    self.save_jobs()

            # Sleep until the next job is due (or max 60s for responsiveness).
            # CancelledError here means clean shutdown via stop().
            try:
                await asyncio.sleep(self._compute_sleep())
            except asyncio.CancelledError:
                return

    @staticmethod
    def _is_no_suggestions(text: str) -> bool:
        """Check if a response is the NO_SUGGESTIONS sentinel.

        Models sometimes narrate before writing the keyword, so we check
        each line independently (case-insensitive, underscores normalized).
        """
        return any(
            ln.strip().upper().replace("_", " ") == "NO SUGGESTIONS"
            for ln in (text or "").strip().splitlines()
        )

    async def _deliver(self, job: Job, text: str) -> None:
        """Deliver job output to a channel via the registered callback."""
        if self._deliver_callback:
            await self._deliver_callback(job, text)
        else:
            log.info(
                f"Scheduler: deliver job '{job.id}' output to"
                f" {job.delivery}:{job.delivery_chat_id} (no delivery callback set)"
            )

    def add_job(self, job_data: dict) -> Job:
        """Add a new job at runtime."""
        prompts_base = self.agents_dir / job_data["agent"] / "prompts"
        job = Job(job_data, prompts_base=prompts_base)
        job.next_run = job.compute_next_run().isoformat()
        self.jobs.append(job)
        self.save_jobs()
        log.info(f"Scheduler: added job '{job.id}'")
        return job

    def remove_job(self, job_id: str) -> bool:
        """Remove a job by ID."""
        before = len(self.jobs)
        self.jobs = [j for j in self.jobs if j.id != job_id]
        if len(self.jobs) < before:
            self.save_jobs()
            log.info(f"Scheduler: removed job '{job_id}'")
            return True
        return False

    async def trigger_job(self, job_id: str) -> str:
        """Manually trigger a job immediately, returning the response text.

        Mirrors the ``_loop`` behavior: routes the prompt, delivers output,
        cleans up the SDK session for isolated-mode jobs, and logs timing.

        Args:
            job_id: The ID of the job to trigger.

        Returns:
            The agent's response text.

        Raises:
            KeyError: If no job with the given ID exists.
        """
        import time

        from .router import InboundMessage

        job = next((j for j in self.jobs if j.id == job_id), None)
        if job is None:
            raise KeyError(f"Job '{job_id}' not found")

        if not job.prompt:
            raise ValueError(f"Job '{job_id}' has no prompt")

        log.info(f"Scheduler: manually triggering job '{job.id}' for agent '{job.agent}'")
        start = time.monotonic()

        from .tracing import trace_cron_job

        with trace_cron_job(job.id, job.agent):
            message = InboundMessage(
                agent=job.agent,
                text=job.prompt,
                source="cron",
                chat_id=job.delivery_chat_id,
                session_key=f"cron:{job.id}",
            )
            outbound = await self.router.route(message)

            # Deliver to channel if configured (suppress NO_SUGGESTIONS)
            if self._is_no_suggestions(outbound.text):
                log.info(f"Scheduler: job '{job.id}' returned NO_SUGGESTIONS — skipping delivery")
            elif job.delivery and job.delivery_chat_id:
                await self._deliver(job, outbound.text)

            job.last_run = datetime.now().isoformat()
            job.status = "ok"
            job.failures = 0
            self.save_jobs()

        # Clean up SDK session for isolated-mode jobs (matches _loop behavior).
        # Without this, manual triggers leave stale connections that accumulate.
        if job.session_mode == "isolated":
            agent = self.router.get_agent(job.agent)
            if agent:
                try:
                    await agent.new_session()
                except (Exception, asyncio.CancelledError) as e:
                    log.debug(f"Scheduler: session cleanup for '{job.agent}' failed (ignored): {e}")

        elapsed = time.monotonic() - start
        log.info(f"Scheduler: job '{job.id}' completed in {elapsed:.1f}s")

        return outbound.text

    def enable_job(self, job_id: str) -> bool:
        """Enable a disabled job so it will be scheduled.

        Always recomputes ``next_run`` from the current time to avoid stale
        values causing an unexpected immediate fire (e.g. job was disabled for
        hours/days and its old ``next_run`` is in the past).

        Args:
            job_id: The ID of the job to enable.

        Returns:
            True if the job was found and enabled, False if not found.
        """
        job = next((j for j in self.jobs if j.id == job_id), None)
        if job is None:
            return False

        job.enabled = True
        # Always recompute next_run from now — a stale value from before the
        # job was disabled would cause immediate firing on re-enable.
        if job.prompt:
            job.next_run = job.compute_next_run().isoformat()
        self.save_jobs()
        log.info(f"Scheduler: enabled job '{job_id}'")
        return True

    def disable_job(self, job_id: str) -> bool:
        """Disable a job so it won't be scheduled (but remains in the job list).

        Args:
            job_id: The ID of the job to disable.

        Returns:
            True if the job was found and disabled, False if not found.
        """
        job = next((j for j in self.jobs if j.id == job_id), None)
        if job is None:
            return False

        job.enabled = False
        self.save_jobs()
        log.info(f"Scheduler: disabled job '{job_id}'")
        return True

    def edit_job(self, job_id: str, **kwargs: Any) -> Job | None:
        """Edit an existing job's fields in place.

        Accepts keyword arguments matching editable job fields:
        ``schedule``, ``prompt``, ``prompt_file``, ``delivery``,
        ``delivery_chat_id``, ``session_mode``, ``enabled``.

        If ``schedule`` is changed, validates the new cron expression and
        recomputes ``next_run``. If ``enabled`` is set to True, ``next_run``
        is recomputed (same as ``enable_job``).

        Args:
            job_id: The ID of the job to edit.
            **kwargs: Fields to update.

        Returns:
            The updated Job, or None if not found.

        Raises:
            InvalidScheduleError: If a new ``schedule`` value is invalid.
            ValueError: If no editable fields are provided.
        """
        editable = {
            "schedule",
            "prompt",
            "prompt_file",
            "delivery",
            "delivery_chat_id",
            "session_mode",
            "enabled",
        }
        updates = {k: v for k, v in kwargs.items() if k in editable and v is not None}
        if not updates:
            raise ValueError("No editable fields provided")

        job = next((j for j in self.jobs if j.id == job_id), None)
        if job is None:
            return None

        # Validate new schedule before applying anything
        if "schedule" in updates:
            try:
                croniter(updates["schedule"])
            except (ValueError, KeyError, TypeError) as e:
                raise InvalidScheduleError(
                    f"Job '{job_id}': invalid cron schedule '{updates['schedule']}': {e}"
                ) from e

        # Resolve prompt_file to actual prompt content
        if updates.get("prompt_file"):
            path = self.agents_dir / job.agent / "prompts" / updates["prompt_file"]
            if path.exists():
                updates["prompt"] = path.read_text().strip()
            else:
                log.warning(f"Job {job_id}: prompt file not found: {path}")

        # Apply updates
        for key, value in updates.items():
            setattr(job, key, value)

        # Recompute next_run when schedule changes or job is re-enabled
        schedule_changed = "schedule" in updates
        just_enabled = updates.get("enabled") is True
        if (schedule_changed or just_enabled) and job.enabled and job.prompt:
            job.next_run = job.compute_next_run().isoformat()

        self.save_jobs()
        log.info(f"Scheduler: edited job '{job_id}' ({', '.join(updates.keys())})")
        return job

    def list_jobs(self) -> list[dict]:
        """List all jobs as dicts."""
        return [j.to_dict() for j in self.jobs]
