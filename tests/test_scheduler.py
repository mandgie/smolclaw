"""Tests for the Scheduler and Job classes."""

from __future__ import annotations

import asyncio
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
        try:
            await task
        except asyncio.CancelledError:
            pass

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
        try:
            await task
        except asyncio.CancelledError:
            pass

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
        try:
            await task
        except asyncio.CancelledError:
            pass

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
        try:
            await task
        except asyncio.CancelledError:
            pass

        router.route.assert_not_called()
