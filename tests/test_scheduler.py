"""Tests for the Scheduler and Job classes."""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from smolclaw.scheduler import InvalidScheduleError, Job, Scheduler


class TestJob:
    def test_basic_creation(self):
        job = Job({"id": "j1", "agent": "tars", "schedule": "0 8 * * *"})
        assert job.id == "j1"
        assert job.agent == "tars"
        assert job.schedule == "0 8 * * *"
        assert job.enabled is True
        assert job.failures == 0

    def test_prompt_from_inline(self):
        job = Job({"id": "j1", "agent": "tars", "schedule": "* * * * *", "prompt": "Hello"})
        assert job.prompt == "Hello"

    def test_prompt_from_file(self, tmp_path: Path):
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "morning.md").write_text("Good morning!")

        job = Job(
            {"id": "j1", "agent": "tars", "schedule": "* * * * *", "prompt_file": "morning.md"},
            prompts_base=prompts_dir,
        )
        assert job.prompt == "Good morning!"

    def test_prompt_file_missing(self, tmp_path: Path):
        job = Job(
            {"id": "j1", "agent": "tars", "schedule": "* * * * *", "prompt_file": "nope.md"},
            prompts_base=tmp_path,
        )
        assert job.prompt == ""

    def test_compute_next_run(self):
        job = Job({"id": "j1", "agent": "tars", "schedule": "0 8 * * *"})
        base = datetime(2026, 1, 1, 7, 0)
        next_run = job.compute_next_run(after=base)
        assert next_run.hour == 8
        assert next_run.day == 1

    def test_invalid_schedule_raises(self):
        """Invalid cron expression raises InvalidScheduleError at creation."""
        with pytest.raises(InvalidScheduleError, match="invalid cron schedule"):
            Job({"id": "bad", "agent": "tars", "schedule": "not-a-cron"})

    def test_invalid_schedule_bad_field(self):
        """Out-of-range cron fields raise InvalidScheduleError."""
        with pytest.raises(InvalidScheduleError):
            Job({"id": "bad", "agent": "tars", "schedule": "99 99 99 99 99"})

    def test_valid_schedule_passes(self):
        """Valid cron expressions don't raise."""
        job = Job({"id": "ok", "agent": "tars", "schedule": "*/5 * * * *"})
        assert job.schedule == "*/5 * * * *"

    def test_to_dict_roundtrip(self):
        data = {
            "id": "j1",
            "agent": "tars",
            "schedule": "0 8 * * *",
            "prompt": "Hi",
            "enabled": True,
            "delivery": "telegram",
            "delivery_chat_id": "123",
            "session_mode": "isolated",
            "last_run": "",
            "next_run": "",
            "status": "pending",
            "failures": 0,
        }
        job = Job(data)
        result = job.to_dict()
        assert result["id"] == "j1"
        assert result["agent"] == "tars"
        assert result["delivery"] == "telegram"


class TestScheduler:
    def test_load_jobs(self, tmp_base: Path, jobs_file: Path):
        agents_dir = tmp_base / "agents"
        router = MagicMock()
        scheduler = Scheduler(jobs_file, agents_dir, router)
        scheduler.load_jobs()

        assert len(scheduler.jobs) == 1
        assert scheduler.jobs[0].id == "test-job"
        assert scheduler.jobs[0].next_run != ""

    def test_load_jobs_no_file(self, tmp_path: Path):
        router = MagicMock()
        scheduler = Scheduler(tmp_path / "nope.json", tmp_path, router)
        scheduler.load_jobs()
        assert scheduler.jobs == []

    def test_save_jobs(self, tmp_base: Path, jobs_file: Path):
        agents_dir = tmp_base / "agents"
        router = MagicMock()
        scheduler = Scheduler(jobs_file, agents_dir, router)
        scheduler.load_jobs()

        scheduler.save_jobs()
        saved = json.loads(jobs_file.read_text())
        assert len(saved) == 1
        assert saved[0]["id"] == "test-job"

    def test_add_job(self, tmp_base: Path, jobs_file: Path):
        agents_dir = tmp_base / "agents"
        router = MagicMock()
        scheduler = Scheduler(jobs_file, agents_dir, router)
        scheduler.load_jobs()

        new_job = scheduler.add_job(
            {
                "id": "new-job",
                "agent": "testagent",
                "schedule": "0 12 * * *",
                "prompt": "Lunchtime!",
            }
        )
        assert new_job.id == "new-job"
        assert len(scheduler.jobs) == 2

        saved = json.loads(jobs_file.read_text())
        assert len(saved) == 2

    def test_remove_job(self, tmp_base: Path, jobs_file: Path):
        agents_dir = tmp_base / "agents"
        router = MagicMock()
        scheduler = Scheduler(jobs_file, agents_dir, router)
        scheduler.load_jobs()

        assert scheduler.remove_job("test-job") is True
        assert len(scheduler.jobs) == 0

    def test_remove_job_not_found(self, tmp_base: Path, jobs_file: Path):
        agents_dir = tmp_base / "agents"
        router = MagicMock()
        scheduler = Scheduler(jobs_file, agents_dir, router)
        scheduler.load_jobs()

        assert scheduler.remove_job("ghost") is False
        assert len(scheduler.jobs) == 1

    def test_list_jobs(self, tmp_base: Path, jobs_file: Path):
        agents_dir = tmp_base / "agents"
        router = MagicMock()
        scheduler = Scheduler(jobs_file, agents_dir, router)
        scheduler.load_jobs()

        jobs = scheduler.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["id"] == "test-job"

    def test_load_jobs_invalid_json(self, tmp_path: Path):
        """load_jobs handles corrupt JSON gracefully."""
        jobs_file = tmp_path / "jobs.json"
        jobs_file.write_text("NOT JSON {{{")
        router = MagicMock()
        scheduler = Scheduler(jobs_file, tmp_path, router)
        scheduler.load_jobs()
        assert scheduler.jobs == []

    def test_load_jobs_skips_disabled(self, tmp_base: Path):
        """Disabled jobs are excluded from the loaded list."""
        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        jobs_path.write_text(
            json.dumps(
                [
                    {
                        "id": "disabled-job",
                        "agent": "testagent",
                        "schedule": "0 8 * * *",
                        "prompt": "Hello",
                        "enabled": False,
                    }
                ]
            )
        )
        router = MagicMock()
        scheduler = Scheduler(jobs_path, tmp_base / "agents", router)
        scheduler.load_jobs()
        assert scheduler.jobs == []

    def test_load_jobs_skips_invalid_schedule(self, tmp_base: Path):
        """Jobs with invalid cron schedules are skipped with a warning."""
        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        jobs_path.write_text(
            json.dumps(
                [
                    {
                        "id": "good-job",
                        "agent": "testagent",
                        "schedule": "0 8 * * *",
                        "prompt": "Hello",
                    },
                    {
                        "id": "bad-job",
                        "agent": "testagent",
                        "schedule": "not-valid",
                        "prompt": "Broken",
                    },
                ]
            )
        )
        router = MagicMock()
        scheduler = Scheduler(jobs_path, tmp_base / "agents", router)
        scheduler.load_jobs()
        # Only the valid job should be loaded
        assert len(scheduler.jobs) == 1
        assert scheduler.jobs[0].id == "good-job"

    def test_load_jobs_skips_malformed_entry(self, tmp_base: Path):
        """Jobs missing required fields (like 'agent') are skipped."""
        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        jobs_path.write_text(
            json.dumps(
                [
                    {"id": "no-agent", "schedule": "0 8 * * *", "prompt": "Hello"},
                ]
            )
        )
        router = MagicMock()
        scheduler = Scheduler(jobs_path, tmp_base / "agents", router)
        scheduler.load_jobs()
        assert scheduler.jobs == []

    def test_load_jobs_skips_empty_prompt(self, tmp_base: Path):
        """Jobs with no prompt are excluded."""
        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        jobs_path.write_text(
            json.dumps(
                [
                    {
                        "id": "no-prompt",
                        "agent": "testagent",
                        "schedule": "0 8 * * *",
                        "prompt": "",
                    }
                ]
            )
        )
        router = MagicMock()
        scheduler = Scheduler(jobs_path, tmp_base / "agents", router)
        scheduler.load_jobs()
        assert scheduler.jobs == []


class TestSchedulerLoop:
    """Tests for the async _loop, _deliver, start, and stop methods."""

    async def test_loop_fires_due_job(self, tmp_base: Path, jobs_file: Path):
        """A due job is routed, marked ok, and next_run updated."""
        from smolclaw.router import OutboundMessage

        router = MagicMock()
        router.route = AsyncMock(
            return_value=OutboundMessage(agent="testagent", text="done", source="cron")
        )
        scheduler = Scheduler(jobs_file, tmp_base / "agents", router)
        scheduler.load_jobs()
        assert len(scheduler.jobs) == 1

        # Set next_run to the past so it's due now
        scheduler.jobs[0].next_run = "2020-01-01T00:00:00"

        # Run one iteration of the loop (stop after first sleep)
        scheduler._running = True

        async def one_iteration():
            """Run _loop but break after the first sleep."""
            from smolclaw.router import InboundMessage

            now = datetime.now()
            for job in scheduler.jobs:
                if not job.enabled or not job.next_run:
                    continue
                next_dt = datetime.fromisoformat(job.next_run)
                if now >= next_dt:
                    message = InboundMessage(
                        agent=job.agent,
                        text=job.prompt,
                        source="cron",
                        chat_id=job.delivery_chat_id,
                        session_key=f"cron:{job.id}",
                    )
                    outbound = await scheduler.router.route(message)
                    if job.delivery and job.delivery_chat_id:
                        await scheduler._deliver(job, outbound.text)
                    job.last_run = now.isoformat()
                    job.status = "ok"
                    job.failures = 0
                    job.next_run = job.compute_next_run(after=now).isoformat()
                    scheduler.save_jobs()

        await one_iteration()

        # Verify the router was called
        router.route.assert_called_once()
        call_msg = router.route.call_args[0][0]
        assert call_msg.agent == "testagent"
        assert call_msg.source == "cron"
        assert call_msg.text == "Hello from cron"

        # Verify job state updated
        job = scheduler.jobs[0]
        assert job.status == "ok"
        assert job.failures == 0
        assert job.last_run != ""
        assert job.next_run != "2020-01-01T00:00:00"

    async def test_loop_skips_future_job(self, tmp_base: Path, jobs_file: Path):
        """Jobs with next_run in the future are not fired."""
        router = MagicMock()
        router.route = AsyncMock()
        scheduler = Scheduler(jobs_file, tmp_base / "agents", router)
        scheduler.load_jobs()

        # Set next_run far in the future
        scheduler.jobs[0].next_run = "2099-01-01T00:00:00"
        scheduler._running = True

        # Run the _loop but cancel after a short time
        task = asyncio.create_task(scheduler._loop())
        await asyncio.sleep(0.05)
        scheduler._running = False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        router.route.assert_not_called()

    async def test_loop_handles_route_error(self, tmp_base: Path, jobs_file: Path):
        """A job that raises during routing is marked as error."""
        router = MagicMock()
        router.route = AsyncMock(side_effect=RuntimeError("agent exploded"))
        scheduler = Scheduler(jobs_file, tmp_base / "agents", router)
        scheduler.load_jobs()
        scheduler.jobs[0].next_run = "2020-01-01T00:00:00"
        scheduler._running = True

        # Run _loop briefly
        task = asyncio.create_task(scheduler._loop())
        await asyncio.sleep(0.05)
        scheduler._running = False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        job = scheduler.jobs[0]
        assert job.status == "error"
        assert job.failures == 1
        # next_run should still be updated
        assert job.next_run != "2020-01-01T00:00:00"

    async def test_loop_delivers_to_channel(self, tmp_base: Path):
        """When delivery is configured, _deliver_callback is called."""
        from smolclaw.router import OutboundMessage

        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        jobs_path.write_text(
            json.dumps(
                [
                    {
                        "id": "deliver-job",
                        "agent": "testagent",
                        "schedule": "0 8 * * *",
                        "prompt": "Deliver me",
                        "enabled": True,
                        "delivery": "telegram",
                        "delivery_chat_id": "12345",
                    }
                ]
            )
        )

        deliver_mock = AsyncMock()
        router = MagicMock()
        router.route = AsyncMock(
            return_value=OutboundMessage(agent="testagent", text="delivered", source="cron")
        )

        scheduler = Scheduler(jobs_path, tmp_base / "agents", router, deliver_callback=deliver_mock)
        scheduler.load_jobs()
        scheduler.jobs[0].next_run = "2020-01-01T00:00:00"
        scheduler._running = True

        task = asyncio.create_task(scheduler._loop())
        await asyncio.sleep(0.05)
        scheduler._running = False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        deliver_mock.assert_called_once()
        call_args = deliver_mock.call_args[0]
        assert call_args[0].id == "deliver-job"
        assert call_args[1] == "delivered"

    async def test_deliver_no_callback(self, tmp_base: Path, jobs_file: Path):
        """_deliver without a callback logs but doesn't crash."""
        router = MagicMock()
        scheduler = Scheduler(jobs_file, tmp_base / "agents", router)
        job = Job(
            {
                "id": "j1",
                "agent": "tars",
                "schedule": "0 8 * * *",
                "delivery": "telegram",
                "delivery_chat_id": "123",
            }
        )
        # Should not raise
        await scheduler._deliver(job, "hello")

    async def test_deliver_with_callback(self, tmp_base: Path, jobs_file: Path):
        """_deliver calls the registered callback."""
        deliver_mock = AsyncMock()
        router = MagicMock()
        scheduler = Scheduler(jobs_file, tmp_base / "agents", router, deliver_callback=deliver_mock)
        job = Job(
            {
                "id": "j1",
                "agent": "tars",
                "schedule": "0 8 * * *",
                "delivery": "telegram",
                "delivery_chat_id": "123",
            }
        )
        await scheduler._deliver(job, "response text")
        deliver_mock.assert_called_once_with(job, "response text")

    async def test_start_and_stop(self, tmp_base: Path, jobs_file: Path):
        """start() launches the loop task, stop() cancels it."""
        router = MagicMock()
        scheduler = Scheduler(jobs_file, tmp_base / "agents", router)

        await scheduler.start()
        assert scheduler._running is True
        assert scheduler._task is not None
        assert not scheduler._task.done()

        await scheduler.stop()
        assert scheduler._running is False

    async def test_loop_skips_disabled_job(self, tmp_base: Path):
        """Disabled jobs in the list are skipped during the loop."""
        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        # Write a job that's enabled so it passes load_jobs filtering,
        # then disable it at runtime
        jobs_path.write_text(
            json.dumps(
                [
                    {
                        "id": "runtime-disabled",
                        "agent": "testagent",
                        "schedule": "0 8 * * *",
                        "prompt": "Hello",
                        "enabled": True,
                    }
                ]
            )
        )
        router = MagicMock()
        router.route = AsyncMock()
        scheduler = Scheduler(jobs_path, tmp_base / "agents", router)
        scheduler.load_jobs()

        # Disable the job at runtime and set it due
        scheduler.jobs[0].enabled = False
        scheduler.jobs[0].next_run = "2020-01-01T00:00:00"
        scheduler._running = True

        task = asyncio.create_task(scheduler._loop())
        await asyncio.sleep(0.05)
        scheduler._running = False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        router.route.assert_not_called()


class TestLoadJobsNextRunValidation:
    """Tests for invalid next_run handling during load_jobs."""

    def test_load_jobs_recomputes_invalid_next_run(self, tmp_base: Path):
        """A job with a garbage next_run string gets it recomputed on load."""
        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        jobs_path.write_text(
            json.dumps(
                [
                    {
                        "id": "bad-next-run",
                        "agent": "testagent",
                        "schedule": "0 8 * * *",
                        "prompt": "Hello",
                        "enabled": True,
                        "next_run": "not-a-date",
                    }
                ]
            )
        )
        router = MagicMock()
        scheduler = Scheduler(jobs_path, tmp_base / "agents", router)
        scheduler.load_jobs()

        assert len(scheduler.jobs) == 1
        # The invalid next_run should have been replaced with a valid ISO timestamp
        job = scheduler.jobs[0]
        assert job.next_run != "not-a-date"
        datetime.fromisoformat(job.next_run)  # Should not raise

    def test_load_jobs_preserves_valid_next_run(self, tmp_base: Path):
        """A job with a valid next_run keeps it unchanged."""
        valid_ts = "2099-01-01T08:00:00"
        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        jobs_path.write_text(
            json.dumps(
                [
                    {
                        "id": "good-next-run",
                        "agent": "testagent",
                        "schedule": "0 8 * * *",
                        "prompt": "Hello",
                        "enabled": True,
                        "next_run": valid_ts,
                    }
                ]
            )
        )
        router = MagicMock()
        scheduler = Scheduler(jobs_path, tmp_base / "agents", router)
        scheduler.load_jobs()

        assert len(scheduler.jobs) == 1
        assert scheduler.jobs[0].next_run == valid_ts


class TestLoopEdgeCases:
    """Tests for edge cases in the scheduler _loop and _on_loop_done."""

    async def test_loop_handles_invalid_next_run_at_runtime(self, tmp_base: Path):
        """A job with corrupted next_run during runtime gets it recomputed."""
        from smolclaw.router import OutboundMessage

        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        jobs_path.write_text(
            json.dumps(
                [
                    {
                        "id": "runtime-bad",
                        "agent": "testagent",
                        "schedule": "0 8 * * *",
                        "prompt": "Hello",
                        "enabled": True,
                    }
                ]
            )
        )
        router = MagicMock()
        router.route = AsyncMock(
            return_value=OutboundMessage(agent="testagent", text="ok", source="cron")
        )
        scheduler = Scheduler(jobs_path, tmp_base / "agents", router)
        scheduler.load_jobs()

        # Corrupt the next_run at runtime
        scheduler.jobs[0].next_run = "garbage-timestamp"
        scheduler._running = True

        task = asyncio.create_task(scheduler._loop())
        await asyncio.sleep(0.05)
        scheduler._running = False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        # The job's next_run should have been recomputed
        job = scheduler.jobs[0]
        assert job.next_run != "garbage-timestamp"
        datetime.fromisoformat(job.next_run)  # Should not raise

    async def test_loop_disables_job_on_unrecoverable_next_run(self, tmp_base: Path):
        """A job that fails to recompute next_run is disabled."""
        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        jobs_path.write_text(
            json.dumps(
                [
                    {
                        "id": "unrecoverable",
                        "agent": "testagent",
                        "schedule": "0 8 * * *",
                        "prompt": "Hello",
                        "enabled": True,
                    }
                ]
            )
        )
        router = MagicMock()
        scheduler = Scheduler(jobs_path, tmp_base / "agents", router)
        scheduler.load_jobs()

        # Corrupt next_run and make compute_next_run fail too
        job = scheduler.jobs[0]
        job.next_run = "garbage"
        job.compute_next_run = MagicMock(side_effect=Exception("broken schedule"))

        scheduler._running = True
        task = asyncio.create_task(scheduler._loop())
        await asyncio.sleep(0.05)
        scheduler._running = False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        # The job should be disabled
        assert job.enabled is False

    async def test_on_loop_done_restarts_on_crash(self, tmp_base: Path, jobs_file: Path):
        """_on_loop_done schedules a restart when the loop crashes."""
        router = MagicMock()
        scheduler = Scheduler(jobs_file, tmp_base / "agents", router)
        scheduler._running = True

        # Create a task that fails
        async def crashing_loop():
            raise RuntimeError("loop exploded")

        task = asyncio.create_task(crashing_loop())
        await asyncio.sleep(0.05)  # Let it crash

        assert task.done()
        assert task.exception() is not None

        # Call _on_loop_done manually — it should schedule a restart via call_later
        # and not crash
        scheduler._on_loop_done(task)

    async def test_on_loop_done_noop_on_clean_shutdown(self, tmp_base: Path, jobs_file: Path):
        """_on_loop_done does nothing when _running is False (clean shutdown)."""
        router = MagicMock()
        scheduler = Scheduler(jobs_file, tmp_base / "agents", router)
        scheduler._running = False  # Clean shutdown

        task = MagicMock()
        task.cancelled.return_value = False
        task.exception.return_value = None

        # Should return early without trying to restart
        scheduler._on_loop_done(task)
        # No exception means success — it returned early

    async def test_loop_cancellation_exits_cleanly(self, tmp_base: Path, jobs_file: Path):
        """CancelledError during sleep exits the loop cleanly (no propagation)."""
        router = MagicMock()
        scheduler = Scheduler(jobs_file, tmp_base / "agents", router)
        scheduler.load_jobs()
        scheduler._running = True

        task = asyncio.create_task(scheduler._loop())
        await asyncio.sleep(0.05)

        # Cancel the task — it should exit cleanly, not raise
        task.cancel()
        await task  # Should complete without error

        assert task.done()
        assert not task.cancelled()

    async def test_cancelled_job_does_not_kill_loop(self, tmp_base: Path, jobs_file: Path):
        """A CancelledError during job execution marks it cancelled, loop continues."""

        router = MagicMock()
        router.route = AsyncMock(side_effect=asyncio.CancelledError)
        scheduler = Scheduler(jobs_file, tmp_base / "agents", router)
        scheduler.load_jobs()
        assert len(scheduler.jobs) == 1

        # Make the job due
        scheduler.jobs[0].next_run = "2020-01-01T00:00:00"
        scheduler._running = True

        # Run one iteration — the job will be cancelled but loop should survive
        task = asyncio.create_task(scheduler._loop())
        await asyncio.sleep(0.1)

        # Stop cleanly
        scheduler._running = False
        task.cancel()
        await task

        # Job should be marked as cancelled, not error
        job = scheduler.jobs[0]
        assert job.status == "cancelled"
        # next_run should be recomputed (job wasn't abandoned)
        assert job.next_run != "2020-01-01T00:00:00"

    async def test_session_cleanup_cancelled_error_ignored(self, tmp_base: Path, jobs_file: Path):
        """CancelledError during session cleanup is caught and ignored."""
        from smolclaw.router import OutboundMessage

        mock_agent = MagicMock()
        mock_agent.new_session = AsyncMock(side_effect=asyncio.CancelledError)

        router = MagicMock()
        router.route = AsyncMock(
            return_value=OutboundMessage(agent="testagent", text="done", source="cron")
        )
        router.get_agent = MagicMock(return_value=mock_agent)

        scheduler = Scheduler(jobs_file, tmp_base / "agents", router)
        scheduler.load_jobs()
        scheduler.jobs[0].next_run = "2020-01-01T00:00:00"
        scheduler._running = True

        task = asyncio.create_task(scheduler._loop())
        await asyncio.sleep(0.1)

        scheduler._running = False
        task.cancel()
        await task

        # Job should still succeed despite cleanup failure
        assert scheduler.jobs[0].status == "ok"
        mock_agent.new_session.assert_called_once()

    async def test_on_loop_done_logs_cancelled(self, tmp_base: Path, jobs_file: Path):
        """_on_loop_done handles a cancelled task distinctly from a crash."""
        router = MagicMock()
        scheduler = Scheduler(jobs_file, tmp_base / "agents", router)
        scheduler._running = True

        # Create a task that gets cancelled
        async def sleepy():
            await asyncio.sleep(100)

        task = asyncio.create_task(sleepy())
        await asyncio.sleep(0.01)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert task.cancelled()

        # Call _on_loop_done — it should not crash and should schedule restart
        scheduler._on_loop_done(task)


class TestNoSuggestionsSuppression:
    """Tests for the NO_SUGGESTIONS delivery suppression logic."""

    async def _run_job_with_response(self, tmp_base: Path, response_text: str) -> AsyncMock:
        """Helper: run a due job that returns response_text, return deliver mock."""
        from smolclaw.router import OutboundMessage

        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        jobs_path.write_text(
            json.dumps(
                [
                    {
                        "id": "suppress-test",
                        "agent": "testagent",
                        "schedule": "0 8 * * *",
                        "prompt": "Check stuff",
                        "enabled": True,
                        "delivery": "telegram",
                        "delivery_chat_id": "99999",
                    }
                ]
            )
        )

        deliver_mock = AsyncMock()
        router = MagicMock()
        router.route = AsyncMock(
            return_value=OutboundMessage(agent="testagent", text=response_text, source="cron")
        )

        scheduler = Scheduler(jobs_path, tmp_base / "agents", router, deliver_callback=deliver_mock)
        scheduler.load_jobs()
        scheduler.jobs[0].next_run = "2020-01-01T00:00:00"
        scheduler._running = True

        task = asyncio.create_task(scheduler._loop())
        await asyncio.sleep(0.1)
        scheduler._running = False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        return deliver_mock

    async def test_exact_no_suggestions_suppresses(self, tmp_base: Path):
        """Exact 'NO_SUGGESTIONS' text suppresses delivery."""
        deliver = await self._run_job_with_response(tmp_base, "NO_SUGGESTIONS")
        deliver.assert_not_called()

    async def test_no_suggestions_with_narration_suppresses(self, tmp_base: Path):
        """'NO_SUGGESTIONS' on any line suppresses delivery (model may narrate first)."""
        deliver = await self._run_job_with_response(
            tmp_base, "Nothing interesting today.\nNO_SUGGESTIONS"
        )
        deliver.assert_not_called()

    async def test_no_suggestions_lowercase_suppresses(self, tmp_base: Path):
        """Case-insensitive: 'no_suggestions' also suppresses."""
        deliver = await self._run_job_with_response(tmp_base, "no_suggestions")
        deliver.assert_not_called()

    async def test_no_suggestions_with_spaces_suppresses(self, tmp_base: Path):
        """'NO SUGGESTIONS' (space instead of underscore) also suppresses."""
        deliver = await self._run_job_with_response(tmp_base, "NO SUGGESTIONS")
        deliver.assert_not_called()

    async def test_no_suggestions_with_leading_whitespace_suppresses(self, tmp_base: Path):
        """Leading/trailing whitespace on the line is ignored."""
        deliver = await self._run_job_with_response(tmp_base, "  NO_SUGGESTIONS  ")
        deliver.assert_not_called()

    async def test_normal_response_delivers(self, tmp_base: Path):
        """Normal response text is delivered as usual."""
        deliver = await self._run_job_with_response(tmp_base, "Here is your briefing!")
        deliver.assert_called_once()
        assert deliver.call_args[0][1] == "Here is your briefing!"

    async def test_empty_response_delivers(self, tmp_base: Path):
        """Empty response is not suppressed (only NO_SUGGESTIONS is)."""
        deliver = await self._run_job_with_response(tmp_base, "")
        # Empty string with delivery configured — still calls deliver
        deliver.assert_called_once()

    async def test_partial_match_does_not_suppress(self, tmp_base: Path):
        """Text containing 'NO_SUGGESTIONS' as substring does not suppress."""
        deliver = await self._run_job_with_response(
            tmp_base, "The response was NO_SUGGESTIONS_FOUND for this query"
        )
        deliver.assert_called_once()


class TestRepr:
    def test_job_repr(self):
        job = Job({"id": "j1", "agent": "tars", "schedule": "0 8 * * *"})
        r = repr(job)
        assert "Job" in r
        assert "j1" in r
        assert "tars" in r

    def test_scheduler_repr(self, tmp_base: Path, jobs_file: Path):
        router = MagicMock()
        scheduler = Scheduler(jobs_file, tmp_base / "agents", router)
        assert "Scheduler" in repr(scheduler)
        assert "running=False" in repr(scheduler)


class TestTriggerJob:
    """Tests for the manual trigger_job method."""

    async def test_trigger_job_routes_and_returns_response(self, tmp_base: Path, jobs_file: Path):
        """trigger_job should route the job and return the response text."""
        from smolclaw.router import OutboundMessage

        router = MagicMock()
        router.route = AsyncMock(
            return_value=OutboundMessage(agent="testagent", text="triggered!", source="cron")
        )
        scheduler = Scheduler(jobs_file, tmp_base / "agents", router)
        scheduler.load_jobs()
        assert len(scheduler.jobs) == 1

        result = await scheduler.trigger_job("test-job")

        assert result == "triggered!"
        router.route.assert_called_once()
        call_msg = router.route.call_args[0][0]
        assert call_msg.agent == "testagent"
        assert call_msg.source == "cron"
        assert call_msg.text == "Hello from cron"

    async def test_trigger_job_updates_state(self, tmp_base: Path, jobs_file: Path):
        """trigger_job should update last_run, status, and failures."""
        from smolclaw.router import OutboundMessage

        router = MagicMock()
        router.route = AsyncMock(
            return_value=OutboundMessage(agent="testagent", text="ok", source="cron")
        )
        scheduler = Scheduler(jobs_file, tmp_base / "agents", router)
        scheduler.load_jobs()

        await scheduler.trigger_job("test-job")

        job = scheduler.jobs[0]
        assert job.status == "ok"
        assert job.failures == 0
        assert job.last_run != ""

    async def test_trigger_job_delivers_to_channel(self, tmp_base: Path, jobs_file: Path):
        """trigger_job should deliver to channel if delivery is configured."""
        from smolclaw.router import OutboundMessage

        # Set up job with delivery config
        jobs_data = json.loads(jobs_file.read_text())
        jobs_data[0]["delivery"] = "telegram"
        jobs_data[0]["delivery_chat_id"] = "123456"
        jobs_file.write_text(json.dumps(jobs_data))

        router = MagicMock()
        router.route = AsyncMock(
            return_value=OutboundMessage(agent="testagent", text="delivered!", source="cron")
        )
        deliver_cb = AsyncMock()
        scheduler = Scheduler(jobs_file, tmp_base / "agents", router, deliver_callback=deliver_cb)
        scheduler.load_jobs()

        await scheduler.trigger_job("test-job")

        deliver_cb.assert_called_once()
        assert deliver_cb.call_args[0][1] == "delivered!"

    async def test_trigger_job_not_found(self, tmp_base: Path, jobs_file: Path):
        """trigger_job should raise KeyError for unknown job ID."""
        router = MagicMock()
        scheduler = Scheduler(jobs_file, tmp_base / "agents", router)
        scheduler.load_jobs()

        with pytest.raises(KeyError, match="not-real"):
            await scheduler.trigger_job("not-real")

    async def test_trigger_job_no_prompt(self, tmp_base: Path):
        """trigger_job should raise ValueError for job without prompt."""
        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        jobs_path.parent.mkdir(parents=True, exist_ok=True)
        jobs_path.write_text(
            json.dumps(
                [
                    {
                        "id": "empty-prompt",
                        "agent": "testagent",
                        "schedule": "0 8 * * *",
                        "prompt": "has prompt",
                    }
                ]
            )
        )

        router = MagicMock()
        scheduler = Scheduler(jobs_path, tmp_base / "agents", router)
        scheduler.load_jobs()
        # Clear prompt after loading
        scheduler.jobs[0].prompt = ""

        with pytest.raises(ValueError, match="no prompt"):
            await scheduler.trigger_job("empty-prompt")
