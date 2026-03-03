"""Cron scheduler — fires job triggers through the router as regular messages."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from croniter import croniter

if TYPE_CHECKING:
    from .router import Router

log = logging.getLogger("smolclaw")


class InvalidScheduleError(ValueError):
    """Raised when a cron schedule expression is invalid."""


class Job:
    """A scheduled job definition."""

    def __init__(self, data: dict[str, Any], prompts_base: Path | None = None):
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
        prompt_file = data.get("prompt_file", "")
        self.prompt: str = data.get("prompt", "")
        if prompt_file and prompts_base:
            path = prompts_base / prompt_file
            if path.exists():
                self.prompt = path.read_text().strip()
            else:
                log.warning(f"Job {self.id}: prompt file not found: {path}")

        # Runtime state
        self.last_run: str = data.get("last_run", "")
        self.next_run: str = data.get("next_run", "")
        self.status: str = data.get("status", "pending")
        self.failures: int = data.get("failures", 0)

    def compute_next_run(self, after: datetime | None = None) -> datetime:
        """Compute the next run time from the cron expression."""
        base = after or datetime.now()
        cron = croniter(self.schedule, base)
        return cron.get_next(datetime)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "agent": self.agent,
            "schedule": self.schedule,
            "prompt": self.prompt,
            "enabled": self.enabled,
            "delivery": self.delivery,
            "delivery_chat_id": self.delivery_chat_id,
            "session_mode": self.session_mode,
            "last_run": self.last_run,
            "next_run": self.next_run,
            "status": self.status,
            "failures": self.failures,
        }


class Scheduler:
    """Cron scheduler that fires job triggers through the router."""

    def __init__(
        self,
        jobs_path: Path,
        agents_dir: Path,
        router: Router,
        deliver_callback: Callable[[Job, str], Awaitable[None]] | None = None,
    ):
        self.jobs_path = jobs_path
        self.agents_dir = agents_dir
        self.router = router
        self._deliver_callback = deliver_callback
        self.jobs: list[Job] = []
        self._task: asyncio.Task | None = None
        self._running = False

    def load_jobs(self) -> None:
        """Load jobs from jobs.json."""
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

            if job.enabled and job.prompt:
                # Compute next run if not set
                if not job.next_run:
                    job.next_run = job.compute_next_run().isoformat()
                self.jobs.append(job)
        log.info(f"Scheduler: loaded {len(self.jobs)} jobs")

    def save_jobs(self) -> None:
        """Persist jobs back to jobs.json."""
        self.jobs_path.parent.mkdir(parents=True, exist_ok=True)
        data = [j.to_dict() for j in self.jobs]
        self.jobs_path.write_text(json.dumps(data, indent=2))

    async def start(self) -> None:
        """Start the scheduler loop."""
        self.load_jobs()
        self._running = True
        self._task = asyncio.create_task(self._loop())
        log.info("Scheduler: started")

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("Scheduler: stopped")

    async def _loop(self) -> None:
        """Main scheduler loop — check every 30 seconds for due jobs."""
        from .router import InboundMessage

        while self._running:
            now = datetime.now()

            for job in self.jobs:
                if not job.enabled or not job.next_run:
                    continue

                next_dt = datetime.fromisoformat(job.next_run)
                if now >= next_dt:
                    log.info(f"Scheduler: firing job '{job.id}' for agent '{job.agent}'")
                    try:
                        message = InboundMessage(
                            agent=job.agent,
                            text=job.prompt,
                            source="cron",
                            chat_id=job.delivery_chat_id,
                            session_key=f"cron:{job.id}",
                        )
                        outbound = await self.router.route(message)

                        # Deliver to channel if configured
                        if job.delivery and job.delivery_chat_id:
                            await self._deliver(job, outbound.text)

                        job.last_run = now.isoformat()
                        job.status = "ok"
                        job.failures = 0
                    except Exception as e:
                        log.error(f"Scheduler: job '{job.id}' failed: {e}")
                        job.status = "error"
                        job.failures += 1

                    # Compute next run
                    job.next_run = job.compute_next_run(after=now).isoformat()
                    self.save_jobs()

            await asyncio.sleep(30)

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

    def list_jobs(self) -> list[dict]:
        """List all jobs as dicts."""
        return [j.to_dict() for j in self.jobs]
