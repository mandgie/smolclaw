"""Shared fixtures for smolclaw tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_base(tmp_path: Path) -> Path:
    """Create a minimal smolclaw home directory for testing."""
    # Shared dirs
    (tmp_path / "shared" / "skills").mkdir(parents=True)
    (tmp_path / "shared" / "cron").mkdir(parents=True)
    (tmp_path / "shared" / "USER.md").write_text("# Test User\nName: Tester\n")

    # Default config
    (tmp_path / "config.yaml").write_text("host: 127.0.0.1\nport: 7890\nlog_level: WARNING\n")

    return tmp_path


@pytest.fixture
def agent_dir(tmp_base: Path) -> Path:
    """Create a single test agent."""
    agent = tmp_base / "agents" / "testagent"
    for subdir in ["skills", "prompts", "context", "channels", "sessions"]:
        (agent / subdir).mkdir(parents=True)

    (agent / "agent.yaml").write_text(
        "name: testagent\n"
        "model: claude-sonnet-4-6\n"
        "channels: {}\n"
        "memory:\n"
        "  enabled: true\n"
        "  cross_agent: false\n"
    )
    (agent / "soul.md").write_text("# TESTAGENT\nYou are a test agent.\n")
    (agent / "agents.md").write_text("# TESTAGENT — Rules\nBe helpful.\n")

    return agent


@pytest.fixture
def jobs_file(tmp_base: Path) -> Path:
    """Create a jobs.json with one test job."""
    jobs_path = tmp_base / "shared" / "cron" / "jobs.json"
    jobs = [
        {
            "id": "test-job",
            "agent": "testagent",
            "schedule": "0 8 * * *",
            "prompt": "Hello from cron",
            "prompt_file": "",
            "enabled": True,
            "delivery": "",
            "delivery_chat_id": "",
            "session_mode": "isolated",
            "last_run": "",
            "next_run": "",
            "status": "pending",
            "failures": 0,
        }
    ]
    jobs_path.write_text(json.dumps(jobs))
    return jobs_path
