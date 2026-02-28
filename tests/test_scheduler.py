"""Tests for the Scheduler and Job classes."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from smolclaw.scheduler import Job, Scheduler


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
