"""Tests for the FastAPI REST API."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from smolclaw.api import (
    _extract_assistant_text,
    _extract_user_text,
    _parse_session_messages,
    _parse_session_meta,
    _sessions_dir_for_agent,
    create_app,
)
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
    agent.last_cost_usd = None
    agent.last_usage = None
    agent.last_structured_output = None
    agent.last_num_turns = None
    agent.last_duration_ms = None
    agent.last_stop_reason = None

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
        data = resp.json()
        assert data["response"] == "Hello from the agent!"
        assert data["cost_usd"] is None
        assert data["usage"] is None
        assert data["structured_output"] is None
        assert data["num_turns"] is None
        assert data["duration_ms"] is None
        assert data["stop_reason"] is None
        mock_gateway.send.assert_awaited_once_with("testagent", "Hello")

    def test_send_returns_cost_and_usage(self, client, mock_gateway):
        agent = mock_gateway.agents["testagent"]
        agent.last_cost_usd = 0.015
        agent.last_usage = {"input_tokens": 200, "output_tokens": 100}
        agent.last_structured_output = {"answer": "42"}
        agent.last_num_turns = 3
        agent.last_duration_ms = 5200
        agent.last_stop_reason = "end_turn"

        resp = client.post("/api/agents/testagent/send", json={"text": "Hi"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["cost_usd"] == 0.015
        assert data["usage"]["input_tokens"] == 200
        assert data["structured_output"]["answer"] == "42"
        assert data["num_turns"] == 3
        assert data["duration_ms"] == 5200
        assert data["stop_reason"] == "end_turn"

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


class TestSearchMemory:
    def test_search_auto_mode(self, client, mock_gateway):
        agent = mock_gateway.agents["testagent"]
        agent.memory.add_fact("Python is a programming language", category="tech")
        agent.memory.add_fact("Stockholm weather is cold", category="weather")

        resp = client.get("/api/agents/testagent/memory/search?q=Python")
        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "Python"
        assert data["mode"] == "auto"
        assert len(data["results"]) >= 1
        assert any("Python" in r["content"] for r in data["results"])

    def test_search_with_limit(self, client, mock_gateway):
        agent = mock_gateway.agents["testagent"]
        for i in range(5):
            agent.memory.add_fact(f"Fact about topic {i}")

        resp = client.get("/api/agents/testagent/memory/search?q=topic&limit=2")
        assert resp.status_code == 200
        assert len(resp.json()["results"]) <= 2

    def test_search_vector_mode_without_embed(self, client, mock_gateway):
        """Vector mode returns empty when no embed_fn is configured."""
        agent = mock_gateway.agents["testagent"]
        agent.memory.add_fact("Test fact")

        resp = client.get("/api/agents/testagent/memory/search?q=test&mode=vector")
        assert resp.status_code == 200
        assert resp.json()["results"] == []
        assert resp.json()["mode"] == "vector"

    def test_search_hybrid_mode(self, client, mock_gateway):
        agent = mock_gateway.agents["testagent"]
        agent.memory.add_fact("Hybrid search test fact")

        resp = client.get("/api/agents/testagent/memory/search?q=Hybrid&mode=hybrid")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "hybrid"
        # Hybrid falls back to FTS when no vector is available
        assert len(data["results"]) >= 1

    def test_search_404_unknown_agent(self, client):
        resp = client.get("/api/agents/nobody/memory/search?q=test")
        assert resp.status_code == 404

    def test_search_400_no_memory(self, client, mock_gateway):
        mock_gateway.agents["testagent"].memory = None
        resp = client.get("/api/agents/testagent/memory/search?q=test")
        assert resp.status_code == 400

    def test_search_empty_results(self, client, mock_gateway):
        resp = client.get("/api/agents/testagent/memory/search?q=nonexistent_xyz")
        assert resp.status_code == 200
        assert resp.json()["results"] == []


class TestAddFact:
    def test_adds_fact(self, client, mock_gateway):
        resp = client.post(
            "/api/agents/testagent/memory/facts",
            json={"content": "New fact via API", "category": "test"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "created"
        assert isinstance(data["id"], int)

        # Verify fact exists
        facts = mock_gateway.agents["testagent"].memory.list_facts()
        assert any(f["content"] == "New fact via API" for f in facts)

    def test_adds_fact_default_category(self, client, mock_gateway):
        resp = client.post(
            "/api/agents/testagent/memory/facts",
            json={"content": "Fact without category"},
        )
        assert resp.status_code == 200
        facts = mock_gateway.agents["testagent"].memory.list_facts()
        fact = next(f for f in facts if f["content"] == "Fact without category")
        assert fact["category"] == "general"

    def test_422_empty_content(self, client):
        resp = client.post(
            "/api/agents/testagent/memory/facts",
            json={"content": ""},
        )
        assert resp.status_code == 422

    def test_404_unknown_agent(self, client):
        resp = client.post(
            "/api/agents/nobody/memory/facts",
            json={"content": "test"},
        )
        assert resp.status_code == 404

    def test_400_no_memory(self, client, mock_gateway):
        mock_gateway.agents["testagent"].memory = None
        resp = client.post(
            "/api/agents/testagent/memory/facts",
            json={"content": "test"},
        )
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


class TestMemoryStats:
    def test_returns_stats(self, client, mock_gateway):
        agent = mock_gateway.agents["testagent"]
        agent.memory.add_fact("A fact")
        agent.memory.add_chunk("Q", "A")

        resp = client.get("/api/agents/testagent/memory/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["facts"] >= 1
        assert data["chunks"] >= 1
        assert "agent" in data

    def test_stats_empty_memory(self, client, mock_gateway):
        resp = client.get("/api/agents/testagent/memory/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["facts"] == 0
        assert data["chunks"] == 0

    def test_404_unknown_agent(self, client):
        resp = client.get("/api/agents/nobody/memory/stats")
        assert resp.status_code == 404

    def test_400_no_memory(self, client, mock_gateway):
        mock_gateway.agents["testagent"].memory = None
        resp = client.get("/api/agents/testagent/memory/stats")
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


# --- Session helper tests ---


class TestExtractUserText:
    def test_string_content(self):
        assert _extract_user_text("Hello world") == "Hello world"

    def test_list_with_text_blocks(self):
        content = [{"type": "text", "text": "Hello"}, {"type": "text", "text": "world"}]
        assert _extract_user_text(content) == "Hello world"

    def test_list_with_string_items(self):
        content = ["Hello", "world"]
        assert _extract_user_text(content) == "Hello world"

    def test_skips_tool_result_blocks(self):
        content = [
            {"type": "text", "text": "Query"},
            {"type": "tool_result", "content": "result data"},
        ]
        assert _extract_user_text(content) == "Query"

    def test_non_string_non_list(self):
        assert _extract_user_text(42) == ""
        assert _extract_user_text(None) == ""


class TestExtractAssistantText:
    def test_string_content(self):
        assert _extract_assistant_text("Response") == "Response"

    def test_text_blocks(self):
        content = [{"type": "text", "text": "Hello"}]
        assert _extract_assistant_text(content) == "Hello"

    def test_tool_use_blocks(self):
        content = [
            {"type": "text", "text": "Let me check."},
            {"type": "tool_use", "name": "Read"},
        ]
        assert _extract_assistant_text(content) == "Let me check.\n[Tool: Read]"

    def test_tool_use_missing_name(self):
        content = [{"type": "tool_use"}]
        assert _extract_assistant_text(content) == "[Tool: unknown]"

    def test_non_string_non_list(self):
        assert _extract_assistant_text(42) == ""


class TestSessionsDir:
    def test_computes_correct_path(self):
        agent = MagicMock()
        agent.info.path.resolve.return_value = Path("/Users/test/.smolclaw/agents/tars")
        result = _sessions_dir_for_agent(agent)
        assert result == Path.home() / ".claude" / "projects" / "-Users-test--smolclaw-agents-tars"


class TestParseSessionMeta:
    def test_parses_valid_session(self, tmp_path):
        session = tmp_path / "abc123.jsonl"
        lines = [
            json.dumps(
                {
                    "type": "user",
                    "timestamp": "2026-03-06T10:00:00Z",
                    "message": {"content": "Hello agent"},
                }
            ),
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": "2026-03-06T10:00:01Z",
                    "message": {"content": [{"type": "text", "text": "Hi!"}]},
                }
            ),
        ]
        session.write_text("\n".join(lines))

        meta = _parse_session_meta(session)
        assert meta is not None
        assert meta["id"] == "abc123"
        assert meta["messages"] == 2
        assert meta["created"] == "2026-03-06T10:00:00Z"
        assert meta["updated"] == "2026-03-06T10:00:01Z"
        assert meta["preview"] == "Hello agent"

    def test_empty_session_returns_none(self, tmp_path):
        session = tmp_path / "empty.jsonl"
        session.write_text("")
        assert _parse_session_meta(session) is None

    def test_only_system_messages_returns_none(self, tmp_path):
        session = tmp_path / "sys.jsonl"
        lines = [json.dumps({"type": "system", "message": {"content": "init"}})]
        session.write_text("\n".join(lines))
        assert _parse_session_meta(session) is None

    def test_handles_malformed_json(self, tmp_path):
        session = tmp_path / "bad.jsonl"
        valid = json.dumps(
            {
                "type": "user",
                "timestamp": "2026-03-06T10:00:00Z",
                "message": {"content": "Valid"},
            }
        )
        session.write_text("not json\n" + valid)
        meta = _parse_session_meta(session)
        assert meta is not None
        assert meta["messages"] == 1

    def test_truncates_long_preview(self, tmp_path):
        session = tmp_path / "long.jsonl"
        long_msg = "A" * 200
        entry = {
            "type": "user",
            "timestamp": "2026-03-06T10:00:00Z",
            "message": {"content": long_msg},
        }
        lines = [json.dumps(entry)]
        session.write_text("\n".join(lines))
        meta = _parse_session_meta(session)
        assert len(meta["preview"]) == 120


class TestParseSessionMessages:
    def test_parses_user_and_assistant(self, tmp_path):
        session = tmp_path / "conv.jsonl"
        ts = "2026-03-06T10:00:0"
        lines = [
            json.dumps(
                {
                    "type": "user",
                    "timestamp": f"{ts}0Z",
                    "message": {"content": "What's 2+2?"},
                }
            ),
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": f"{ts}1Z",
                    "message": {
                        "content": [{"type": "text", "text": "4"}],
                        "model": "claude-sonnet-4-6",
                    },
                }
            ),
        ]
        session.write_text("\n".join(lines))

        messages = _parse_session_messages(session)
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["text"] == "What's 2+2?"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["text"] == "4"
        assert messages[1]["model"] == "claude-sonnet-4-6"

    def test_skips_system_entries(self, tmp_path):
        session = tmp_path / "sys.jsonl"
        lines = [
            json.dumps({"type": "system", "message": {"content": "init"}}),
            json.dumps({"type": "user", "message": {"content": "Hi"}}),
        ]
        session.write_text("\n".join(lines))
        messages = _parse_session_messages(session)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_skips_empty_text(self, tmp_path):
        session = tmp_path / "empty.jsonl"
        lines = [json.dumps({"type": "user", "message": {"content": ""}})]
        session.write_text("\n".join(lines))
        messages = _parse_session_messages(session)
        assert len(messages) == 0


# --- Session API endpoint tests ---


class TestListSessions:
    def test_returns_sessions(self, client, mock_gateway, tmp_path):
        # Create a fake sessions directory
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        session_file = sessions_dir / "abc-123.jsonl"
        entry = {
            "type": "user",
            "timestamp": "2026-03-06T10:00:00Z",
            "message": {"content": "Hello"},
        }
        session_file.write_text(json.dumps(entry))

        with patch("smolclaw.api._sessions_dir_for_agent", return_value=sessions_dir):
            resp = client.get("/api/agents/testagent/sessions")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["id"] == "abc-123"
        assert data["sessions"][0]["preview"] == "Hello"

    def test_returns_empty_when_no_dir(self, client, mock_gateway, tmp_path):
        nonexistent = tmp_path / "no-such-dir"
        with patch("smolclaw.api._sessions_dir_for_agent", return_value=nonexistent):
            resp = client.get("/api/agents/testagent/sessions")
        assert resp.status_code == 200
        assert resp.json()["sessions"] == []

    def test_404_unknown_agent(self, client):
        resp = client.get("/api/agents/nobody/sessions")
        assert resp.status_code == 404


class TestGetSession:
    def test_returns_session_messages(self, client, mock_gateway, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        session_file = sessions_dir / "abc-def-123.jsonl"
        lines = [
            json.dumps({"type": "user", "message": {"content": "Hi"}}),
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": "Hello!"}]},
                }
            ),
        ]
        session_file.write_text("\n".join(lines))

        with patch("smolclaw.api._sessions_dir_for_agent", return_value=sessions_dir):
            resp = client.get("/api/agents/testagent/sessions/abc-def-123")

        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "abc-def-123"
        assert len(data["messages"]) == 2

    def test_400_invalid_session_id(self, client):
        resp = client.get("/api/agents/testagent/sessions/DROP_TABLE;--")
        assert resp.status_code == 400

    def test_404_unknown_agent(self, client):
        resp = client.get("/api/agents/nobody/sessions/abc-123")
        assert resp.status_code == 404

    def test_404_missing_session(self, client, mock_gateway, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        with patch("smolclaw.api._sessions_dir_for_agent", return_value=sessions_dir):
            resp = client.get("/api/agents/testagent/sessions/abc-123")
        assert resp.status_code == 404
