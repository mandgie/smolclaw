"""Tests for the FastAPI REST API."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from smolclaw.api import create_app
from smolclaw.memory import Memory

# --- Fixtures ---


@pytest.fixture
def mock_gateway(tmp_path: Path):
    """Create a mock Gateway with one agent and a scheduler."""
    gw = MagicMock()

    # Mock agent
    agent = MagicMock()
    agent.name = "testagent"
    agent.model = "claude-sonnet-4-6"
    agent.is_connected = False
    agent.info.config.channels = {}
    agent.info.skills = ["skill1"]
    agent.info.soul = "You are a test agent."
    agent.info.agents_md = "Be helpful."
    agent.info.context_files = {"notes": "some notes"}
    agent.memory = Memory(tmp_path / "memory.db", agent="testagent")
    agent.new_session = AsyncMock()

    gw.agents = {"testagent": agent}

    # Mock router
    gw.router.get_agent.side_effect = lambda name: gw.agents.get(name)

    # Mock send (async)
    gw.send = AsyncMock(return_value="Hello from the agent!")

    # Mock scheduler
    scheduler = MagicMock()
    scheduler.jobs = []
    scheduler.list_jobs.return_value = []
    scheduler.remove_job.side_effect = lambda jid: jid == "existing-job"
    gw.scheduler = scheduler

    return gw


@pytest.fixture
def client(mock_gateway):
    """FastAPI test client."""
    app = create_app(mock_gateway)
    return TestClient(app)


# --- Agent endpoint tests ---


class TestListAgents:
    def test_returns_agent_list(self, client):
        resp = client.get("/api/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["agents"]) == 1
        agent = data["agents"][0]
        assert agent["name"] == "testagent"
        assert agent["model"] == "claude-sonnet-4-6"
        assert agent["skills"] == 1

    def test_empty_when_no_agents(self, mock_gateway):
        mock_gateway.agents = {}
        app = create_app(mock_gateway)
        client = TestClient(app)
        resp = client.get("/api/agents")
        assert resp.json()["agents"] == []


class TestGetAgent:
    def test_returns_agent_detail(self, client):
        resp = client.get("/api/agents/testagent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "testagent"
        assert data["soul"] == "You are a test agent."
        assert data["agents_md"] == "Be helpful."
        assert "notes" in data["context_files"]

    def test_404_unknown_agent(self, client):
        resp = client.get("/api/agents/nobody")
        assert resp.status_code == 404


class TestSendMessage:
    def test_sends_and_returns_response(self, client, mock_gateway):
        resp = client.post("/api/agents/testagent/send", json={"text": "Hello"})
        assert resp.status_code == 200
        assert resp.json()["response"] == "Hello from the agent!"
        mock_gateway.send.assert_awaited_once_with("testagent", "Hello")

    def test_422_missing_text(self, client):
        resp = client.post("/api/agents/testagent/send", json={})
        assert resp.status_code == 422

    def test_500_on_agent_error(self, client, mock_gateway):
        mock_gateway.send = AsyncMock(side_effect=RuntimeError("boom"))
        resp = client.post("/api/agents/testagent/send", json={"text": "Hi"})
        assert resp.status_code == 500


class TestNewSession:
    def test_clears_session(self, client, mock_gateway):
        resp = client.post("/api/agents/testagent/new-session")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        mock_gateway.agents["testagent"].new_session.assert_awaited_once()

    def test_404_unknown_agent(self, client):
        resp = client.post("/api/agents/nobody/new-session")
        assert resp.status_code == 404


# --- Memory endpoint tests ---


class TestListFacts:
    def test_returns_facts(self, client, mock_gateway, tmp_path):
        agent = mock_gateway.agents["testagent"]
        agent.memory.add_fact("Test fact", category="tech")
        resp = client.get("/api/agents/testagent/memory/facts")
        assert resp.status_code == 200
        facts = resp.json()["facts"]
        assert len(facts) == 1
        assert facts[0]["content"] == "Test fact"

    def test_filter_by_category(self, client, mock_gateway):
        agent = mock_gateway.agents["testagent"]
        agent.memory.add_fact("Tech fact", category="tech")
        agent.memory.add_fact("Personal fact", category="personal")
        resp = client.get("/api/agents/testagent/memory/facts?category=tech")
        assert resp.status_code == 200
        facts = resp.json()["facts"]
        assert len(facts) == 1
        assert facts[0]["category"] == "tech"

    def test_404_unknown_agent(self, client):
        resp = client.get("/api/agents/nobody/memory/facts")
        assert resp.status_code == 404

    def test_400_no_memory(self, client, mock_gateway):
        mock_gateway.agents["testagent"].memory = None
        resp = client.get("/api/agents/testagent/memory/facts")
        assert resp.status_code == 400


class TestDeleteFact:
    def test_deletes_fact(self, client, mock_gateway):
        agent = mock_gateway.agents["testagent"]
        fact_id = agent.memory.add_fact("Delete me")
        resp = client.delete(f"/api/agents/testagent/memory/facts/{fact_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    def test_404_unknown_fact(self, client):
        resp = client.delete("/api/agents/testagent/memory/facts/9999")
        assert resp.status_code == 404

    def test_404_unknown_agent(self, client):
        resp = client.delete("/api/agents/nobody/memory/facts/1")
        assert resp.status_code == 404

    def test_400_no_memory(self, client, mock_gateway):
        mock_gateway.agents["testagent"].memory = None
        resp = client.delete("/api/agents/testagent/memory/facts/1")
        assert resp.status_code == 400


class TestClearMemory:
    def test_clears_memory(self, client, mock_gateway):
        agent = mock_gateway.agents["testagent"]
        agent.memory.add_fact("Fact 1")
        agent.memory.add_chunk("Q", "A")
        resp = client.delete("/api/agents/testagent/memory")
        assert resp.status_code == 200
        data = resp.json()
        assert data["facts_deleted"] == 1
        assert data["chunks_deleted"] == 1

    def test_404_unknown_agent(self, client):
        resp = client.delete("/api/agents/nobody/memory")
        assert resp.status_code == 404

    def test_400_no_memory(self, client, mock_gateway):
        mock_gateway.agents["testagent"].memory = None
        resp = client.delete("/api/agents/testagent/memory")
        assert resp.status_code == 400


# --- Cron endpoint tests ---


class TestListJobs:
    def test_returns_jobs(self, client):
        resp = client.get("/api/cron/jobs")
        assert resp.status_code == 200
        assert resp.json()["jobs"] == []

    def test_no_scheduler(self, client, mock_gateway):
        mock_gateway.scheduler = None
        resp = client.get("/api/cron/jobs")
        assert resp.json()["jobs"] == []


class TestAddJob:
    def test_adds_job(self, client, mock_gateway):
        job_data = {
            "id": "new-job",
            "agent": "testagent",
            "schedule": "0 9 * * *",
            "prompt": "Good morning",
        }
        mock_job = MagicMock()
        mock_job.to_dict.return_value = job_data
        mock_gateway.scheduler.add_job.return_value = mock_job

        resp = client.post("/api/cron/jobs", json=job_data)
        assert resp.status_code == 200
        assert resp.json()["job"]["id"] == "new-job"

    def test_500_no_scheduler(self, client, mock_gateway):
        mock_gateway.scheduler = None
        resp = client.post(
            "/api/cron/jobs",
            json={"id": "x", "agent": "a", "schedule": "0 * * * *"},
        )
        assert resp.status_code == 500


class TestRemoveJob:
    def test_removes_existing_job(self, client):
        resp = client.delete("/api/cron/jobs/existing-job")
        assert resp.status_code == 200
        assert resp.json()["status"] == "removed"

    def test_404_unknown_job(self, client):
        resp = client.delete("/api/cron/jobs/nope")
        assert resp.status_code == 404

    def test_500_no_scheduler(self, client, mock_gateway):
        mock_gateway.scheduler = None
        resp = client.delete("/api/cron/jobs/any")
        assert resp.status_code == 500


# --- Health & Dashboard ---


class TestHealth:
    def test_returns_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["agents"] == 1
        assert data["channels"] == 0

    def test_includes_version(self, client):
        resp = client.get("/api/health")
        data = resp.json()
        assert "version" in data
        assert data["version"] == "0.1.0"


class TestDashboard:
    def test_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "smolclaw" in resp.text.lower()
