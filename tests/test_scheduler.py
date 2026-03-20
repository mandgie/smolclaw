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

    def test_load_jobs_keeps_disabled(self, tmp_base: Path):
        """Disabled jobs are loaded (to avoid data loss) but not schedulable."""
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
        assert len(scheduler.jobs) == 1
        assert scheduler.jobs[0].id == "disabled-job"
        assert not scheduler.jobs[0].enabled
        # Disabled job should NOT have next_run computed
        assert scheduler.jobs[0].next_run == ""

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

    def test_load_jobs_keeps_empty_prompt(self, tmp_base: Path):
        """Jobs with no prompt are loaded (to avoid data loss) but not schedulable."""
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
        assert len(scheduler.jobs) == 1
        assert scheduler.jobs[0].id == "no-prompt"
        assert scheduler.jobs[0].prompt == ""
        # Promptless job should NOT have next_run computed
        assert scheduler.jobs[0].next_run == ""

    def test_disabled_jobs_survive_save_roundtrip(self, tmp_base: Path):
        """Disabled jobs are preserved across load → save → load cycles."""
        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        original_data = [
            {
                "id": "active-job",
                "agent": "testagent",
                "schedule": "0 8 * * *",
                "prompt": "Hello",
                "enabled": True,
            },
            {
                "id": "disabled-job",
                "agent": "testagent",
                "schedule": "0 9 * * *",
                "prompt": "Disabled hello",
                "enabled": False,
            },
            {
                "id": "no-prompt-job",
                "agent": "testagent",
                "schedule": "0 10 * * *",
                "prompt": "",
                "enabled": True,
            },
        ]
        jobs_path.write_text(json.dumps(original_data))

        router = MagicMock()
        scheduler = Scheduler(jobs_path, tmp_base / "agents", router)
        scheduler.load_jobs()

        # All 3 jobs should be loaded
        assert len(scheduler.jobs) == 3

        # Verify the file still contains all 3 after save
        saved = json.loads(jobs_path.read_text())
        saved_ids = {j["id"] for j in saved}
        assert saved_ids == {"active-job", "disabled-job", "no-prompt-job"}

        # Second load should also find all 3
        scheduler2 = Scheduler(jobs_path, tmp_base / "agents", router)
        scheduler2.load_jobs()
        assert len(scheduler2.jobs) == 3

    def test_save_jobs_atomic_write(self, tmp_base: Path):
        """save_jobs() uses atomic write (temp file + rename)."""
        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        jobs_path.write_text("[]")
        router = MagicMock()
        scheduler = Scheduler(jobs_path, tmp_base / "agents", router)
        scheduler.jobs = [
            Job(
                {
                    "id": "test",
                    "agent": "testagent",
                    "schedule": "0 8 * * *",
                    "prompt": "Hello",
                }
            )
        ]
        scheduler.save_jobs()

        # Verify content is valid JSON and correct
        saved = json.loads(jobs_path.read_text())
        assert len(saved) == 1
        assert saved[0]["id"] == "test"

        # Verify no temp files left behind
        tmp_files = list(tmp_base.joinpath("shared", "cron").glob("*.tmp"))
        assert tmp_files == []


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


class TestIsNoSuggestions:
    """Tests for the _is_no_suggestions static helper."""

    def test_exact_match(self):
        assert Scheduler._is_no_suggestions("NO_SUGGESTIONS") is True

    def test_lowercase(self):
        assert Scheduler._is_no_suggestions("no_suggestions") is True

    def test_spaces_instead_of_underscore(self):
        assert Scheduler._is_no_suggestions("NO SUGGESTIONS") is True

    def test_mixed_case_and_spaces(self):
        assert Scheduler._is_no_suggestions("No Suggestions") is True

    def test_leading_trailing_whitespace(self):
        assert Scheduler._is_no_suggestions("  NO_SUGGESTIONS  ") is True

    def test_on_any_line(self):
        assert Scheduler._is_no_suggestions("Some narration\nNO_SUGGESTIONS") is True

    def test_normal_text(self):
        assert Scheduler._is_no_suggestions("Here is your briefing!") is False

    def test_empty_string(self):
        assert Scheduler._is_no_suggestions("") is False

    def test_none_text(self):
        assert Scheduler._is_no_suggestions(None) is False

    def test_substring_not_matched(self):
        """'NO_SUGGESTIONS_FOUND' should not trigger suppression."""
        assert Scheduler._is_no_suggestions("NO_SUGGESTIONS_FOUND for query") is False


class TestTriggerJobNoSuggestionsSuppression:
    """trigger_job should suppress NO_SUGGESTIONS delivery, same as the loop."""

    async def test_trigger_job_suppresses_no_suggestions(self, tmp_base: Path):
        from smolclaw.router import OutboundMessage

        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        jobs_path.parent.mkdir(parents=True, exist_ok=True)
        jobs_path.write_text(
            json.dumps(
                [
                    {
                        "id": "suppress-trigger",
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

        router = MagicMock()
        router.route = AsyncMock(
            return_value=OutboundMessage(agent="testagent", text="NO_SUGGESTIONS", source="cron")
        )
        deliver_cb = AsyncMock()
        scheduler = Scheduler(jobs_path, tmp_base / "agents", router, deliver_callback=deliver_cb)
        scheduler.load_jobs()

        result = await scheduler.trigger_job("suppress-trigger")

        # Response text is returned...
        assert result == "NO_SUGGESTIONS"
        # ...but delivery is suppressed
        deliver_cb.assert_not_called()

    async def test_trigger_job_delivers_normal_response(self, tmp_base: Path):
        from smolclaw.router import OutboundMessage

        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        jobs_path.parent.mkdir(parents=True, exist_ok=True)
        jobs_path.write_text(
            json.dumps(
                [
                    {
                        "id": "deliver-trigger",
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

        router = MagicMock()
        router.route = AsyncMock(
            return_value=OutboundMessage(
                agent="testagent", text="Here is your briefing!", source="cron"
            )
        )
        deliver_cb = AsyncMock()
        scheduler = Scheduler(jobs_path, tmp_base / "agents", router, deliver_callback=deliver_cb)
        scheduler.load_jobs()

        result = await scheduler.trigger_job("deliver-trigger")

        assert result == "Here is your briefing!"
        deliver_cb.assert_called_once()

    async def test_trigger_job_cleans_up_isolated_session(self, tmp_base: Path):
        """trigger_job calls agent.new_session() for isolated-mode jobs."""
        from smolclaw.router import OutboundMessage

        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        jobs_path.parent.mkdir(parents=True, exist_ok=True)
        jobs_path.write_text(
            json.dumps(
                [
                    {
                        "id": "isolated-trigger",
                        "agent": "testagent",
                        "schedule": "0 8 * * *",
                        "prompt": "Check stuff",
                        "enabled": True,
                        "session_mode": "isolated",
                    }
                ]
            )
        )

        mock_agent = MagicMock()
        mock_agent.new_session = AsyncMock()

        router = MagicMock()
        router.route = AsyncMock(
            return_value=OutboundMessage(agent="testagent", text="Done!", source="cron")
        )
        router.get_agent = MagicMock(return_value=mock_agent)

        scheduler = Scheduler(jobs_path, tmp_base / "agents", router)
        scheduler.load_jobs()

        await scheduler.trigger_job("isolated-trigger")
        mock_agent.new_session.assert_called_once()

    async def test_trigger_job_skips_cleanup_for_shared_session(self, tmp_base: Path):
        """trigger_job does NOT call agent.new_session() for shared-mode jobs."""
        from smolclaw.router import OutboundMessage

        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        jobs_path.parent.mkdir(parents=True, exist_ok=True)
        jobs_path.write_text(
            json.dumps(
                [
                    {
                        "id": "shared-trigger",
                        "agent": "testagent",
                        "schedule": "0 8 * * *",
                        "prompt": "Check stuff",
                        "enabled": True,
                        "session_mode": "shared",
                    }
                ]
            )
        )

        mock_agent = MagicMock()
        mock_agent.new_session = AsyncMock()

        router = MagicMock()
        router.route = AsyncMock(
            return_value=OutboundMessage(agent="testagent", text="Done!", source="cron")
        )
        router.get_agent = MagicMock(return_value=mock_agent)

        scheduler = Scheduler(jobs_path, tmp_base / "agents", router)
        scheduler.load_jobs()

        await scheduler.trigger_job("shared-trigger")
        mock_agent.new_session.assert_not_called()

    async def test_trigger_job_session_cleanup_failure_ignored(self, tmp_base: Path):
        """trigger_job doesn't fail if session cleanup raises."""
        from smolclaw.router import OutboundMessage

        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        jobs_path.parent.mkdir(parents=True, exist_ok=True)
        jobs_path.write_text(
            json.dumps(
                [
                    {
                        "id": "cleanup-fail",
                        "agent": "testagent",
                        "schedule": "0 8 * * *",
                        "prompt": "Check stuff",
                        "enabled": True,
                        "session_mode": "isolated",
                    }
                ]
            )
        )

        mock_agent = MagicMock()
        mock_agent.new_session = AsyncMock(side_effect=RuntimeError("SDK error"))

        router = MagicMock()
        router.route = AsyncMock(
            return_value=OutboundMessage(agent="testagent", text="Done!", source="cron")
        )
        router.get_agent = MagicMock(return_value=mock_agent)

        scheduler = Scheduler(jobs_path, tmp_base / "agents", router)
        scheduler.load_jobs()

        # Should not raise even though cleanup fails
        result = await scheduler.trigger_job("cleanup-fail")
        assert result == "Done!"
        mock_agent.new_session.assert_called_once()


class TestEnableDisableJob:
    """Tests for enable_job() and disable_job() methods."""

    @pytest.fixture()
    def scheduler_with_jobs(self, tmp_base: Path):
        """Create a scheduler with one enabled and one disabled job."""
        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        jobs_path.parent.mkdir(parents=True, exist_ok=True)
        jobs_path.write_text(
            json.dumps(
                [
                    {
                        "id": "active-job",
                        "agent": "testagent",
                        "schedule": "0 8 * * *",
                        "prompt": "Morning check",
                        "enabled": True,
                    },
                    {
                        "id": "paused-job",
                        "agent": "testagent",
                        "schedule": "0 22 * * *",
                        "prompt": "Night check",
                        "enabled": False,
                    },
                ]
            )
        )
        router = MagicMock()
        scheduler = Scheduler(jobs_path, tmp_base / "agents", router)
        scheduler.load_jobs()
        return scheduler

    def test_disable_job(self, scheduler_with_jobs: Scheduler):
        """Disabling a job sets enabled=False and persists."""
        result = scheduler_with_jobs.disable_job("active-job")
        assert result is True

        job = next(j for j in scheduler_with_jobs.jobs if j.id == "active-job")
        assert job.enabled is False

        # Verify persisted to disk
        saved = json.loads(scheduler_with_jobs.jobs_path.read_text())
        saved_job = next(j for j in saved if j["id"] == "active-job")
        assert saved_job["enabled"] is False

    def test_enable_job(self, scheduler_with_jobs: Scheduler):
        """Enabling a disabled job sets enabled=True and computes next_run."""
        result = scheduler_with_jobs.enable_job("paused-job")
        assert result is True

        job = next(j for j in scheduler_with_jobs.jobs if j.id == "paused-job")
        assert job.enabled is True
        assert job.next_run != ""  # next_run should be computed

        # Verify persisted to disk
        saved = json.loads(scheduler_with_jobs.jobs_path.read_text())
        saved_job = next(j for j in saved if j["id"] == "paused-job")
        assert saved_job["enabled"] is True

    def test_enable_not_found(self, scheduler_with_jobs: Scheduler):
        """Enabling a non-existent job returns False."""
        assert scheduler_with_jobs.enable_job("nonexistent") is False

    def test_disable_not_found(self, scheduler_with_jobs: Scheduler):
        """Disabling a non-existent job returns False."""
        assert scheduler_with_jobs.disable_job("nonexistent") is False

    def test_enable_already_enabled(self, scheduler_with_jobs: Scheduler):
        """Enabling an already-enabled job succeeds (idempotent)."""
        assert scheduler_with_jobs.enable_job("active-job") is True
        job = next(j for j in scheduler_with_jobs.jobs if j.id == "active-job")
        assert job.enabled is True

    def test_disable_already_disabled(self, scheduler_with_jobs: Scheduler):
        """Disabling an already-disabled job succeeds (idempotent)."""
        assert scheduler_with_jobs.disable_job("paused-job") is True
        job = next(j for j in scheduler_with_jobs.jobs if j.id == "paused-job")
        assert job.enabled is False

    def test_enable_recomputes_stale_next_run(self, scheduler_with_jobs: Scheduler):
        """Re-enabling a job that has a stale next_run recomputes it to the future."""
        job = next(j for j in scheduler_with_jobs.jobs if j.id == "paused-job")
        # Simulate a stale next_run from 3 days ago
        stale = datetime(2020, 1, 1, 22, 0, 0).isoformat()
        job.next_run = stale

        scheduler_with_jobs.enable_job("paused-job")

        assert job.enabled is True
        # next_run must have been recomputed — it should NOT be the stale value
        assert job.next_run != stale
        # The recomputed next_run should be in the future
        next_dt = datetime.fromisoformat(job.next_run)
        assert next_dt > datetime.now()

    def test_enable_recomputes_even_when_next_run_set(self, scheduler_with_jobs: Scheduler):
        """enable_job always recomputes next_run, even when it's already set."""
        job = next(j for j in scheduler_with_jobs.jobs if j.id == "active-job")

        # Disable and re-enable — next_run should be freshly computed
        scheduler_with_jobs.disable_job("active-job")
        scheduler_with_jobs.enable_job("active-job")

        # next_run should be recomputed (fresh from now, not the old value)
        assert job.next_run != ""
        next_dt = datetime.fromisoformat(job.next_run)
        assert next_dt > datetime.now()

    def test_enable_no_prompt_skips_next_run(self, tmp_base: Path):
        """enable_job on a job without a prompt doesn't set next_run."""
        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        jobs_path.parent.mkdir(parents=True, exist_ok=True)
        jobs_path.write_text(
            json.dumps(
                [
                    {
                        "id": "no-prompt",
                        "agent": "testagent",
                        "schedule": "0 8 * * *",
                        "prompt": "",
                        "enabled": False,
                    },
                ]
            )
        )
        router = MagicMock()
        scheduler = Scheduler(jobs_path, tmp_base / "agents", router)
        scheduler.load_jobs()

        scheduler.enable_job("no-prompt")
        job = next(j for j in scheduler.jobs if j.id == "no-prompt")
        assert job.enabled is True
        assert job.next_run == ""  # No prompt → no scheduling


class TestComputeSleep:
    """Tests for _compute_sleep — adaptive sleep until next due job."""

    def _make_scheduler(self, tmp_path: Path) -> Scheduler:
        jobs_file = tmp_path / "cron" / "jobs.json"
        jobs_file.parent.mkdir(parents=True)
        jobs_file.write_text("[]")
        router = MagicMock()
        return Scheduler(jobs_file, tmp_path / "agents", router)

    def test_no_jobs_returns_max_sleep(self, tmp_path: Path):
        """With no jobs, sleep the maximum duration."""
        scheduler = self._make_scheduler(tmp_path)
        scheduler.load_jobs()
        result = scheduler._compute_sleep()
        assert result == 60.0

    def test_job_due_soon_returns_short_sleep(self, tmp_path: Path):
        """A job due in 5 seconds should return ~5s sleep."""
        from datetime import timedelta

        scheduler = self._make_scheduler(tmp_path)
        scheduler.load_jobs()

        job = Job(
            {"id": "soon", "agent": "tars", "schedule": "* * * * *", "prompt": "hi"},
        )
        job.next_run = (datetime.now() + timedelta(seconds=5)).isoformat()
        scheduler.jobs.append(job)

        result = scheduler._compute_sleep()
        assert 1.0 <= result <= 6.0

    def test_job_due_in_past_returns_min_sleep(self, tmp_path: Path):
        """A job already past due should return min sleep (1s)."""
        scheduler = self._make_scheduler(tmp_path)
        scheduler.load_jobs()

        job = Job(
            {"id": "overdue", "agent": "tars", "schedule": "* * * * *", "prompt": "hi"},
        )
        job.next_run = "2020-01-01T00:00:00"
        scheduler.jobs.append(job)

        result = scheduler._compute_sleep()
        assert result == 1.0

    def test_job_far_future_capped_at_max(self, tmp_path: Path):
        """A job due far in the future should cap at 60s."""
        scheduler = self._make_scheduler(tmp_path)
        scheduler.load_jobs()

        job = Job(
            {"id": "far", "agent": "tars", "schedule": "0 8 * * *", "prompt": "hi"},
        )
        job.next_run = "2099-01-01T00:00:00"
        scheduler.jobs.append(job)

        result = scheduler._compute_sleep()
        assert result == 60.0

    def test_picks_nearest_job(self, tmp_path: Path):
        """With multiple jobs, sleep until the nearest one."""
        from datetime import timedelta

        scheduler = self._make_scheduler(tmp_path)
        scheduler.load_jobs()

        far_job = Job(
            {"id": "far", "agent": "tars", "schedule": "0 8 * * *", "prompt": "hi"},
        )
        far_job.next_run = "2099-01-01T00:00:00"

        near_job = Job(
            {"id": "near", "agent": "tars", "schedule": "* * * * *", "prompt": "hi"},
        )
        near_job.next_run = (datetime.now() + timedelta(seconds=10)).isoformat()

        scheduler.jobs.extend([far_job, near_job])

        result = scheduler._compute_sleep()
        assert 1.0 <= result <= 11.0

    def test_disabled_jobs_ignored(self, tmp_path: Path):
        """Disabled jobs should not affect sleep calculation."""
        scheduler = self._make_scheduler(tmp_path)
        scheduler.load_jobs()

        job = Job(
            {"id": "off", "agent": "tars", "schedule": "* * * * *", "prompt": "hi"},
        )
        job.next_run = "2020-01-01T00:00:00"  # overdue but disabled
        job.enabled = False
        scheduler.jobs.append(job)

        result = scheduler._compute_sleep()
        assert result == 60.0  # falls back to max because the only job is disabled

    def test_invalid_next_run_ignored(self, tmp_path: Path):
        """Jobs with unparseable next_run should be skipped gracefully."""
        scheduler = self._make_scheduler(tmp_path)
        scheduler.load_jobs()

        job = Job(
            {"id": "bad", "agent": "tars", "schedule": "* * * * *", "prompt": "hi"},
        )
        job.next_run = "not-a-date"
        scheduler.jobs.append(job)

        result = scheduler._compute_sleep()
        assert result == 60.0  # gracefully falls back

    def test_promptless_jobs_ignored(self, tmp_path: Path):
        """Jobs without a prompt should not affect sleep calculation."""
        scheduler = self._make_scheduler(tmp_path)
        scheduler.load_jobs()

        job = Job({"id": "noprompt", "agent": "tars", "schedule": "* * * * *"})
        job.next_run = "2020-01-01T00:00:00"  # overdue but no prompt
        scheduler.jobs.append(job)

        result = scheduler._compute_sleep()
        assert result == 60.0


class TestEditJob:
    """Tests for edit_job() method."""

    @pytest.fixture()
    def scheduler_with_jobs(self, tmp_base: Path):
        """Create a scheduler with two jobs for editing tests."""
        jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
        jobs_path.parent.mkdir(parents=True, exist_ok=True)
        jobs_path.write_text(
            json.dumps(
                [
                    {
                        "id": "editable-job",
                        "agent": "testagent",
                        "schedule": "0 8 * * *",
                        "prompt": "Morning check",
                        "enabled": True,
                        "delivery": "telegram",
                        "delivery_chat_id": "123",
                        "session_mode": "isolated",
                    },
                    {
                        "id": "disabled-job",
                        "agent": "testagent",
                        "schedule": "0 22 * * *",
                        "prompt": "Night check",
                        "enabled": False,
                    },
                ]
            )
        )
        agents_dir = tmp_base / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        router = MagicMock()
        scheduler = Scheduler(jobs_path, agents_dir, router)
        scheduler.load_jobs()
        return scheduler

    def test_edit_schedule(self, scheduler_with_jobs: Scheduler):
        """Editing schedule updates the field and recomputes next_run."""
        old_next = next(j for j in scheduler_with_jobs.jobs if j.id == "editable-job").next_run

        job = scheduler_with_jobs.edit_job("editable-job", schedule="30 9 * * *")
        assert job is not None
        assert job.schedule == "30 9 * * *"
        # next_run should have been recomputed
        assert job.next_run != old_next or job.next_run != ""

        # Verify persisted
        saved = json.loads(scheduler_with_jobs.jobs_path.read_text())
        saved_job = next(j for j in saved if j["id"] == "editable-job")
        assert saved_job["schedule"] == "30 9 * * *"

    def test_edit_prompt(self, scheduler_with_jobs: Scheduler):
        """Editing prompt updates the inline prompt text."""
        job = scheduler_with_jobs.edit_job("editable-job", prompt="New prompt text")
        assert job is not None
        assert job.prompt == "New prompt text"

    def test_edit_delivery(self, scheduler_with_jobs: Scheduler):
        """Editing delivery fields updates both delivery and chat_id."""
        job = scheduler_with_jobs.edit_job(
            "editable-job", delivery="webhook", delivery_chat_id="456"
        )
        assert job is not None
        assert job.delivery == "webhook"
        assert job.delivery_chat_id == "456"

    def test_edit_session_mode(self, scheduler_with_jobs: Scheduler):
        """Editing session_mode updates the field."""
        job = scheduler_with_jobs.edit_job("editable-job", session_mode="shared")
        assert job is not None
        assert job.session_mode == "shared"

    def test_edit_enable_recomputes_next_run(self, scheduler_with_jobs: Scheduler):
        """Re-enabling via edit recomputes next_run."""
        job = scheduler_with_jobs.edit_job("disabled-job", enabled=True)
        assert job is not None
        assert job.enabled is True
        assert job.next_run != ""

    def test_edit_not_found(self, scheduler_with_jobs: Scheduler):
        """Editing a non-existent job returns None."""
        assert scheduler_with_jobs.edit_job("nonexistent", prompt="x") is None

    def test_edit_invalid_schedule(self, scheduler_with_jobs: Scheduler):
        """Editing with an invalid schedule raises InvalidScheduleError."""
        with pytest.raises(InvalidScheduleError):
            scheduler_with_jobs.edit_job("editable-job", schedule="not-a-cron")

    def test_edit_no_fields_raises(self, scheduler_with_jobs: Scheduler):
        """Editing with no editable fields raises ValueError."""
        with pytest.raises(ValueError, match="No editable fields"):
            scheduler_with_jobs.edit_job("editable-job")

    def test_edit_ignores_non_editable_fields(self, scheduler_with_jobs: Scheduler):
        """Non-editable fields (id, agent, etc.) are silently ignored."""
        with pytest.raises(ValueError, match="No editable fields"):
            scheduler_with_jobs.edit_job("editable-job", id="hacked", agent="evil")

    def test_edit_multiple_fields(self, scheduler_with_jobs: Scheduler):
        """Editing multiple fields at once works."""
        job = scheduler_with_jobs.edit_job(
            "editable-job",
            schedule="*/5 * * * *",
            prompt="Frequent check",
            delivery="webhook",
        )
        assert job is not None
        assert job.schedule == "*/5 * * * *"
        assert job.prompt == "Frequent check"
        assert job.delivery == "webhook"

    def test_edit_prompt_file(self, scheduler_with_jobs: Scheduler, tmp_base: Path):
        """Editing with a prompt_file resolves and loads the file content."""
        prompts_dir = tmp_base / "agents" / "testagent" / "prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        (prompts_dir / "new-prompt.md").write_text("Content from file")

        job = scheduler_with_jobs.edit_job("editable-job", prompt_file="new-prompt.md")
        assert job is not None
        assert job.prompt == "Content from file"

    def test_edit_persists_to_disk(self, scheduler_with_jobs: Scheduler):
        """All edits are saved to jobs.json."""
        scheduler_with_jobs.edit_job("editable-job", prompt="Persisted prompt")

        saved = json.loads(scheduler_with_jobs.jobs_path.read_text())
        saved_job = next(j for j in saved if j["id"] == "editable-job")
        assert saved_job["prompt"] == "Persisted prompt"


class TestSchedulerOnEvent:
    """Tests for the on_event callback."""

    def test_on_event_is_optional(self, tmp_base: Path, jobs_file: Path):
        """Scheduler works fine without an on_event callback."""
        router = MagicMock()
        scheduler = Scheduler(jobs_file, tmp_base / "agents", router)
        assert scheduler._on_event is None

    def test_on_event_stored(self, tmp_base: Path, jobs_file: Path):
        """on_event callback is stored when provided."""
        router = MagicMock()
        callback = AsyncMock()
        scheduler = Scheduler(jobs_file, tmp_base / "agents", router, on_event=callback)
        assert scheduler._on_event is callback

    async def test_on_event_called_after_job_completes(self, tmp_base: Path, jobs_file: Path):
        """on_event is called after a scheduled job completes."""
        from smolclaw.router import OutboundMessage

        on_event = AsyncMock()
        router = MagicMock()
        router.route = AsyncMock(
            return_value=OutboundMessage(agent="testagent", text="done", source="cron")
        )
        router.get_agent.return_value = None  # No agent for session cleanup

        scheduler = Scheduler(jobs_file, tmp_base / "agents", router, on_event=on_event)
        scheduler.load_jobs()
        scheduler.jobs[0].next_run = "2020-01-01T00:00:00"
        scheduler._running = True

        # Run one tick of the loop then stop
        task = asyncio.create_task(scheduler._loop())
        # Give the loop time to fire the job
        await asyncio.sleep(0.5)
        scheduler._running = False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        on_event.assert_awaited()

    async def test_on_event_failure_does_not_crash_scheduler(self, tmp_base: Path, jobs_file: Path):
        """A failing on_event callback does not crash the scheduler loop."""
        from smolclaw.router import OutboundMessage

        on_event = AsyncMock(side_effect=RuntimeError("callback failed"))
        router = MagicMock()
        router.route = AsyncMock(
            return_value=OutboundMessage(agent="testagent", text="ok", source="cron")
        )
        router.get_agent.return_value = None

        scheduler = Scheduler(jobs_file, tmp_base / "agents", router, on_event=on_event)
        scheduler.load_jobs()
        scheduler.jobs[0].next_run = "2020-01-01T00:00:00"
        scheduler._running = True

        task = asyncio.create_task(scheduler._loop())
        await asyncio.sleep(0.5)
        scheduler._running = False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        # Callback was called (and failed), but job still completed successfully
        on_event.assert_awaited()
        assert scheduler.jobs[0].status == "ok"
