"""Tests for smolclaw.agent — Agent class with mocked Claude SDK."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from smolclaw.config import AgentConfig, AgentInfo, MemoryConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_info(
    name: str = "testagent",
    model: str = "claude-sonnet-4-6",
    soul: str = "You are a test agent.",
    agents_md: str = "Be helpful.",
    skills: list[str] | None = None,
    context_files: dict[str, str] | None = None,
    tmp_path: Path | None = None,
) -> AgentInfo:
    """Build a minimal AgentInfo for testing."""
    config = AgentConfig(
        name=name,
        model=model,
        channels={},
        memory=MemoryConfig(enabled=False, cross_agent=False),
    )
    return AgentInfo(
        config=config,
        path=tmp_path or Path("/tmp/fake-agent"),
        soul=soul,
        agents_md=agents_md,
        skills=skills or [],
        context_files=context_files or {},
    )


def _mock_sdk_client(
    response_text: str = "Hello from Claude",
    session_id: str = "sess-001",
    is_error: bool = False,
    error_result: str = "",
    cost_usd: float | None = None,
    usage: dict | None = None,
    structured_output: Any = None,
    stop_reason: str | None = "end_turn",
):
    """Create a mock ClaudeSDKClient that yields a realistic message stream."""
    from smolclaw.agent import AssistantMessage, ResultMessage, TextBlock

    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.query = AsyncMock()

    # Build message stream
    messages = []
    if response_text:
        assistant_msg = MagicMock(spec=AssistantMessage)
        assistant_msg.content = [MagicMock(spec=TextBlock, text=response_text)]
        messages.append(assistant_msg)

    result_msg = MagicMock(spec=ResultMessage)
    result_msg.session_id = session_id
    result_msg.is_error = is_error
    result_msg.result = error_result
    result_msg.total_cost_usd = cost_usd
    result_msg.usage = usage
    result_msg.structured_output = structured_output
    result_msg.stop_reason = stop_reason
    result_msg.num_turns = 2
    result_msg.duration_ms = 3500
    result_msg.duration_api_ms = 3000
    messages.append(result_msg)

    async def receive_response():
        for msg in messages:
            yield msg

    client.receive_response = receive_response
    return client


# ---------------------------------------------------------------------------
# Tests: __init__
# ---------------------------------------------------------------------------


class TestAgentInit:
    def test_basic_init(self):
        from smolclaw.agent import Agent

        info = _make_info()
        agent = Agent(info, user_md="# User context")
        assert agent.name == "testagent"
        assert agent.model == "claude-sonnet-4-6"
        assert agent.user_md == "# User context"
        assert agent.memory is None
        assert agent.is_connected is False
        assert agent._session_id is None

    def test_defaults(self):
        from smolclaw.agent import Agent

        info = _make_info()
        agent = Agent(info)
        assert agent.user_md == ""


# ---------------------------------------------------------------------------
# Tests: build_system_prompt
# ---------------------------------------------------------------------------


class TestBuildSystemPrompt:
    def test_includes_all_sections(self):
        from smolclaw.agent import Agent

        info = _make_info(
            soul="# SOUL\nI am TARS.",
            agents_md="# AGENTS\nRule one.",
            skills=["# Skill: git\nGit commands."],
            context_files={"notes.md": "Some notes here."},
        )
        agent = Agent(info, user_md="# User\nMagnus")
        prompt = agent.build_system_prompt()

        assert "# User\nMagnus" in prompt
        assert "# SOUL\nI am TARS." in prompt
        assert "# AGENTS\nRule one." in prompt
        assert "# Skill: git" in prompt
        assert "--- notes.md ---\nSome notes here." in prompt
        assert "Agent: testagent" in prompt
        assert "Model: claude-sonnet-4-6" in prompt

    def test_omits_empty_sections(self):
        from smolclaw.agent import Agent

        info = _make_info(soul="", agents_md="", skills=[], context_files={})
        agent = Agent(info, user_md="")
        prompt = agent.build_system_prompt()

        # Should still have runtime section
        assert "Agent: testagent" in prompt
        # But no soul or agents_md markers
        lines = prompt.strip().split("\n")
        assert lines[0].startswith("--- Runtime ---")

    def test_runtime_includes_date_and_workspace(self):
        from smolclaw.agent import Agent

        info = _make_info(soul="", agents_md="")
        agent = Agent(info)
        prompt = agent.build_system_prompt()

        assert "Today:" in prompt
        assert "Workspace:" in prompt

    def test_peers_included_in_prompt(self):
        from smolclaw.agent import Agent

        info = _make_info(soul="", agents_md="")
        agent = Agent(info)
        agent.peers = [
            {"name": "coach", "model": "claude-sonnet-4-6", "description": "Fitness coach"},
            {"name": "writer", "model": "claude-haiku-4-5-20251001", "description": ""},
        ]
        prompt = agent.build_system_prompt()

        assert "Peer Agents" in prompt
        assert "**coach** (claude-sonnet-4-6) — Fitness coach" in prompt
        assert "**writer** (claude-haiku-4-5-20251001)" in prompt
        assert "curl" in prompt

    def test_no_peers_section_when_empty(self):
        from smolclaw.agent import Agent

        info = _make_info(soul="", agents_md="")
        agent = Agent(info)
        agent.peers = []
        prompt = agent.build_system_prompt()

        assert "Peer Agents" not in prompt

    def test_gateway_url_in_peer_section(self):
        from smolclaw.agent import Agent

        info = _make_info(soul="", agents_md="")
        agent = Agent(info)
        agent.gateway_url = "http://10.0.0.1:9999"
        agent.peers = [{"name": "other", "model": "sonnet", "description": ""}]
        prompt = agent.build_system_prompt()

        assert "http://10.0.0.1:9999" in prompt
        assert "localhost:7890" not in prompt

    def test_peers_default_empty(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        assert agent.peers == []
        assert agent.gateway_url == "http://localhost:7890"


# ---------------------------------------------------------------------------
# Tests: connect
# ---------------------------------------------------------------------------


class TestConnect:
    @pytest.mark.asyncio
    async def test_connect_success(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        mock_client = _mock_sdk_client()

        with patch("smolclaw.agent.ClaudeSDKClient", return_value=mock_client):
            result = await agent.connect()

        assert result is True
        assert agent.is_connected is True
        mock_client.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_already_connected(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        mock_client = _mock_sdk_client()

        with patch("smolclaw.agent.ClaudeSDKClient", return_value=mock_client):
            await agent.connect()
            # Second connect should be a no-op
            result = await agent.connect()

        assert result is True
        # Only called once since already connected
        mock_client.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_cli_error_retries_without_resume(self):
        from smolclaw.agent import Agent, CLIConnectionError

        agent = Agent(_make_info())

        call_count = 0
        clients = []

        def make_client(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            client = _mock_sdk_client()
            if call_count == 1:
                # First call (with resume) fails
                client.connect = AsyncMock(side_effect=CLIConnectionError("stale"))
            clients.append(client)
            return client

        with patch("smolclaw.agent.ClaudeSDKClient", side_effect=make_client):
            result = await agent.connect(resume_id="old-session")

        assert result is True
        assert call_count == 2  # retried once without resume

    @pytest.mark.asyncio
    async def test_connect_cli_error_no_resume_fails(self):
        from smolclaw.agent import Agent, CLIConnectionError

        agent = Agent(_make_info())

        mock_client = _mock_sdk_client()
        mock_client.connect = AsyncMock(side_effect=CLIConnectionError("no cli"))

        with patch("smolclaw.agent.ClaudeSDKClient", return_value=mock_client):
            result = await agent.connect(resume_id=None)

        assert result is False
        assert agent.is_connected is False

    @pytest.mark.asyncio
    async def test_connect_generic_error(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())

        mock_client = _mock_sdk_client()
        mock_client.connect = AsyncMock(side_effect=RuntimeError("boom"))

        with patch("smolclaw.agent.ClaudeSDKClient", return_value=mock_client):
            result = await agent.connect()

        assert result is False
        assert agent.is_connected is False
        assert agent._client is None


# ---------------------------------------------------------------------------
# Tests: send / _send_internal
# ---------------------------------------------------------------------------


class TestSend:
    @pytest.mark.asyncio
    async def test_send_returns_response(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        mock_client = _mock_sdk_client(response_text="I'm TARS.", session_id="s-42")

        with patch("smolclaw.agent.ClaudeSDKClient", return_value=mock_client):
            response = await agent.send("Hello")

        assert response == "I'm TARS."
        assert agent._session_id == "s-42"
        mock_client.query.assert_awaited_once_with("Hello")

    @pytest.mark.asyncio
    async def test_send_empty_response(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        mock_client = _mock_sdk_client(response_text="", session_id="s-1")

        with patch("smolclaw.agent.ClaudeSDKClient", return_value=mock_client):
            response = await agent.send("Hi")

        assert response == "(No response)"

    @pytest.mark.asyncio
    async def test_send_with_error_result(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        mock_client = _mock_sdk_client(
            response_text="partial",
            session_id="s-err",
            is_error=True,
            error_result="Token limit exceeded",
        )

        with patch("smolclaw.agent.ClaudeSDKClient", return_value=mock_client):
            response = await agent.send("Long query")

        assert "partial" in response
        assert "[Error: Token limit exceeded]" in response

    @pytest.mark.asyncio
    async def test_send_query_failure_raises(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        mock_client = _mock_sdk_client()
        mock_client.query = AsyncMock(side_effect=RuntimeError("network error"))

        with patch("smolclaw.agent.ClaudeSDKClient", return_value=mock_client):
            with pytest.raises(RuntimeError, match="network error"):
                await agent.send("Hi")

        assert agent.is_connected is False

    @pytest.mark.asyncio
    async def test_send_connection_failure_raises(self):
        from smolclaw.agent import Agent, CLIConnectionError

        agent = Agent(_make_info())

        mock_client = _mock_sdk_client()
        mock_client.connect = AsyncMock(side_effect=CLIConnectionError("nope"))

        with patch("smolclaw.agent.ClaudeSDKClient", return_value=mock_client):
            with pytest.raises(CLIConnectionError):
                await agent.send("Hi")

    @pytest.mark.asyncio
    async def test_send_serialized_per_agent(self):
        """Concurrent sends on the same agent should be serialized by the lock."""
        from smolclaw.agent import Agent

        agent = Agent(_make_info())

        execution_order = []

        async def slow_query(text):
            execution_order.append(f"start-{text}")
            await asyncio.sleep(0.05)
            execution_order.append(f"end-{text}")

        mock_client = _mock_sdk_client(response_text="ok")
        mock_client.query = slow_query
        # Need fresh receive_response for each call
        original_receive = mock_client.receive_response

        call_count = 0

        def fresh_receive():
            nonlocal call_count
            call_count += 1
            return original_receive()

        mock_client.receive_response = fresh_receive

        with patch("smolclaw.agent.ClaudeSDKClient", return_value=mock_client):
            results = await asyncio.gather(
                agent.send("A"),
                agent.send("B"),
            )

        # Both should complete
        assert len(results) == 2
        # First send should finish before second starts (serialized)
        assert execution_order[0] == "start-A"
        assert execution_order[1] == "end-A"


# ---------------------------------------------------------------------------
# Tests: structured output, cost, and usage tracking
# ---------------------------------------------------------------------------


class TestResultMetadata:
    @pytest.mark.asyncio
    async def test_cost_and_usage_tracked(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        mock_client = _mock_sdk_client(
            response_text="Hello",
            cost_usd=0.0042,
            usage={"input_tokens": 100, "output_tokens": 50},
        )

        with patch("smolclaw.agent.ClaudeSDKClient", return_value=mock_client):
            await agent.send("Hi")

        assert agent.last_cost_usd == 0.0042
        assert agent.last_usage == {"input_tokens": 100, "output_tokens": 50}
        assert agent.last_num_turns == 2
        assert agent.last_duration_ms == 3500
        assert agent.last_duration_api_ms == 3000

    @pytest.mark.asyncio
    async def test_structured_output_returned_as_json(self):
        import json

        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        mock_client = _mock_sdk_client(
            response_text="text response",
            structured_output={"name": "test", "value": 42},
        )

        with patch("smolclaw.agent.ClaudeSDKClient", return_value=mock_client):
            response = await agent.send("Get data")

        assert agent.last_structured_output == {"name": "test", "value": 42}
        parsed = json.loads(response)
        assert parsed["name"] == "test"
        assert parsed["value"] == 42

    @pytest.mark.asyncio
    async def test_no_structured_output_returns_text(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        mock_client = _mock_sdk_client(response_text="Plain text")

        with patch("smolclaw.agent.ClaudeSDKClient", return_value=mock_client):
            response = await agent.send("Hi")

        assert response == "Plain text"
        assert agent.last_structured_output is None

    @pytest.mark.asyncio
    async def test_stop_reason_tracked(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        mock_client = _mock_sdk_client(stop_reason="max_tokens")

        with patch("smolclaw.agent.ClaudeSDKClient", return_value=mock_client):
            await agent.send("Hi")

        assert agent.last_stop_reason == "max_tokens"

    @pytest.mark.asyncio
    async def test_stop_reason_end_turn(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        mock_client = _mock_sdk_client(stop_reason="end_turn")

        with patch("smolclaw.agent.ClaudeSDKClient", return_value=mock_client):
            await agent.send("Hi")

        assert agent.last_stop_reason == "end_turn"

    @pytest.mark.asyncio
    async def test_max_tokens_warning_logged(self, caplog):
        """A max_tokens stop_reason should trigger a warning log."""
        import logging

        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        mock_client = _mock_sdk_client(stop_reason="max_tokens")

        with patch("smolclaw.agent.ClaudeSDKClient", return_value=mock_client):
            with caplog.at_level(logging.WARNING, logger="smolclaw"):
                await agent.send("Hi")

        assert "Response truncated (stop_reason=max_tokens)" in caplog.text

    @pytest.mark.asyncio
    async def test_end_turn_no_warning(self, caplog):
        """Normal end_turn stop_reason should NOT trigger a warning."""
        import logging

        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        mock_client = _mock_sdk_client(stop_reason="end_turn")

        with patch("smolclaw.agent.ClaudeSDKClient", return_value=mock_client):
            with caplog.at_level(logging.WARNING, logger="smolclaw"):
                await agent.send("Hi")

        assert "truncated" not in caplog.text

    @pytest.mark.asyncio
    async def test_stream_event_logged(self, caplog):
        """StreamEvent messages should be logged at debug level."""
        import logging

        from smolclaw.agent import Agent, StreamEvent

        agent = Agent(_make_info())
        mock_client = _mock_sdk_client(response_text="Done")

        stream_event = MagicMock(spec=StreamEvent)
        stream_event.event = {"type": "rate_limit", "retry_after": 5}

        original_receive = mock_client.receive_response

        async def receive_with_event():
            yield stream_event
            async for msg in original_receive():
                yield msg

        mock_client.receive_response = receive_with_event

        with patch("smolclaw.agent.ClaudeSDKClient", return_value=mock_client):
            with caplog.at_level(logging.DEBUG, logger="smolclaw"):
                response = await agent.send("Do something")

        assert response == "Done"
        assert "Stream event:" in caplog.text

    @pytest.mark.asyncio
    async def test_cost_none_by_default(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        assert agent.last_cost_usd is None
        assert agent.last_usage is None
        assert agent.last_structured_output is None
        assert agent.last_num_turns is None
        assert agent.last_duration_ms is None
        assert agent.last_duration_api_ms is None
        assert agent.last_stop_reason is None


# ---------------------------------------------------------------------------
# Tests: new_session / shutdown
# ---------------------------------------------------------------------------


class TestSessionManagement:
    @pytest.mark.asyncio
    async def test_new_session_clears_state(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        mock_client = _mock_sdk_client(session_id="s-old")

        with patch("smolclaw.agent.ClaudeSDKClient", return_value=mock_client):
            await agent.send("First message")
            assert agent._session_id == "s-old"

            await agent.new_session()

        assert agent._session_id is None
        assert agent.is_connected is False

    @pytest.mark.asyncio
    async def test_shutdown_disconnects(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        mock_client = _mock_sdk_client()

        with patch("smolclaw.agent.ClaudeSDKClient", return_value=mock_client):
            await agent.connect()
            assert agent.is_connected is True

            await agent.shutdown()

        assert agent.is_connected is False
        mock_client.disconnect.assert_awaited()

    @pytest.mark.asyncio
    async def test_shutdown_when_not_connected(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        # Should not raise
        await agent.shutdown()
        assert agent.is_connected is False


# ---------------------------------------------------------------------------
# Tests: _make_options
# ---------------------------------------------------------------------------


class TestMakeOptions:
    def test_options_basic(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        opts = agent._make_options()
        assert opts.model == "claude-sonnet-4-6"
        assert opts.permission_mode == "bypassPermissions"
        assert opts.cwd == str(agent.info.path)

    def test_options_with_resume(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        opts = agent._make_options(resume_id="sess-123")
        assert opts.resume == "sess-123"

    def test_options_without_resume(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        opts = agent._make_options(resume_id=None)
        assert not hasattr(opts, "resume") or opts.resume is None

    def test_options_with_max_turns(self):
        from smolclaw.agent import Agent

        info = _make_info()
        info.config.max_turns = 10
        agent = Agent(info)
        opts = agent._make_options()
        assert opts.max_turns == 10

    def test_options_without_max_turns(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        opts = agent._make_options()
        assert not hasattr(opts, "max_turns") or opts.max_turns is None

    def test_options_with_max_budget_usd(self):
        from smolclaw.agent import Agent

        info = _make_info()
        info.config.max_budget_usd = 5.0
        agent = Agent(info)
        opts = agent._make_options()
        assert opts.max_budget_usd == 5.0

    def test_options_without_max_budget_usd(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        opts = agent._make_options()
        assert opts.max_budget_usd is None

    def test_options_with_fallback_model(self):
        from smolclaw.agent import Agent

        info = _make_info()
        info.config.fallback_model = "claude-haiku-4-5"
        agent = Agent(info)
        opts = agent._make_options()
        assert opts.fallback_model == "claude-haiku-4-5"

    def test_options_without_fallback_model(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        opts = agent._make_options()
        assert opts.fallback_model is None

    def test_options_with_output_format(self):
        from smolclaw.agent import Agent

        info = _make_info()
        info.config.output_format = {"type": "json", "schema": {"type": "object"}}
        agent = Agent(info)
        opts = agent._make_options()
        assert opts.output_format == {"type": "json", "schema": {"type": "object"}}

    def test_options_without_output_format(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        opts = agent._make_options()
        assert opts.output_format is None

    def test_options_with_file_checkpointing(self):
        from smolclaw.agent import Agent

        info = _make_info()
        info.config.enable_file_checkpointing = True
        agent = Agent(info)
        opts = agent._make_options()
        assert opts.enable_file_checkpointing is True

    def test_options_without_file_checkpointing(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        opts = agent._make_options()
        assert opts.enable_file_checkpointing is False

    def test_options_with_mcp_servers_dict(self):
        from smolclaw.agent import Agent

        info = _make_info()
        info.config.mcp_servers = {"sqlite": {"type": "stdio", "command": "mcp-sqlite"}}
        agent = Agent(info)
        opts = agent._make_options()
        assert opts.mcp_servers == {"sqlite": {"type": "stdio", "command": "mcp-sqlite"}}

    def test_options_with_mcp_servers_path(self, tmp_path):
        from smolclaw.agent import Agent

        info = _make_info(tmp_path=tmp_path)
        mcp_json = tmp_path / "mcp.json"
        mcp_json.write_text('{"servers": {}}')
        info.config.mcp_servers = "mcp.json"
        agent = Agent(info)
        opts = agent._make_options()
        assert opts.mcp_servers == str(tmp_path / "mcp.json")

    def test_options_with_mcp_servers_path_missing(self, tmp_path):
        from smolclaw.agent import Agent

        info = _make_info(tmp_path=tmp_path)
        info.config.mcp_servers = "mcp.json"
        agent = Agent(info)
        opts = agent._make_options()
        # Falls back to the raw string when file doesn't exist
        assert opts.mcp_servers == "mcp.json"

    def test_options_without_mcp_servers(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        opts = agent._make_options()
        # Default is an empty dict from the factory
        assert opts.mcp_servers == {} or opts.mcp_servers is None

    def test_options_with_thinking_adaptive(self):
        from smolclaw.agent import Agent

        info = _make_info()
        info.config.thinking = {"type": "adaptive"}
        agent = Agent(info)
        opts = agent._make_options()
        assert opts.thinking["type"] == "adaptive"

    def test_options_with_thinking_enabled(self):
        from smolclaw.agent import Agent

        info = _make_info()
        info.config.thinking = {"type": "enabled", "budget_tokens": 16000}
        agent = Agent(info)
        opts = agent._make_options()
        assert opts.thinking["type"] == "enabled"
        assert opts.thinking["budget_tokens"] == 16000

    def test_options_with_thinking_disabled(self):
        from smolclaw.agent import Agent

        info = _make_info()
        info.config.thinking = {"type": "disabled"}
        agent = Agent(info)
        opts = agent._make_options()
        assert opts.thinking["type"] == "disabled"

    def test_options_without_thinking(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        opts = agent._make_options()
        assert opts.thinking is None

    def test_options_with_effort(self):
        from smolclaw.agent import Agent

        info = _make_info()
        info.config.effort = "high"
        agent = Agent(info)
        opts = agent._make_options()
        assert opts.effort == "high"

    def test_options_without_effort(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        opts = agent._make_options()
        assert opts.effort is None

    def test_options_with_betas(self):
        from smolclaw.agent import Agent

        info = _make_info()
        info.config.betas = ["context-1m-2025-08-07"]
        agent = Agent(info)
        opts = agent._make_options()
        assert opts.betas == ["context-1m-2025-08-07"]

    def test_options_without_betas(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        opts = agent._make_options()
        assert opts.betas == []

    def test_options_with_add_dirs(self, tmp_path):
        from smolclaw.agent import Agent

        info = _make_info(tmp_path=tmp_path)
        info.config.add_dirs = ["../shared", "extra"]
        agent = Agent(info)
        opts = agent._make_options()
        assert len(opts.add_dirs) == 2
        assert str(tmp_path / "../shared") in opts.add_dirs[0]

    def test_options_without_add_dirs(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        opts = agent._make_options()
        assert opts.add_dirs == []


# ---------------------------------------------------------------------------
# Tests: _build_thinking_config
# ---------------------------------------------------------------------------


class TestBuildThinkingConfig:
    def test_thinking_adaptive(self):
        from smolclaw.agent import Agent

        result = Agent._build_thinking_config({"type": "adaptive"})
        assert result["type"] == "adaptive"

    def test_thinking_enabled_with_budget(self):
        from smolclaw.agent import Agent

        result = Agent._build_thinking_config({"type": "enabled", "budget_tokens": 32000})
        assert result["type"] == "enabled"
        assert result["budget_tokens"] == 32000

    def test_thinking_enabled_default_budget(self):
        from smolclaw.agent import Agent

        result = Agent._build_thinking_config({"type": "enabled"})
        assert result["type"] == "enabled"
        assert result["budget_tokens"] == 0

    def test_thinking_disabled(self):
        from smolclaw.agent import Agent

        result = Agent._build_thinking_config({"type": "disabled"})
        assert result["type"] == "disabled"

    def test_thinking_default_is_adaptive(self):
        from smolclaw.agent import Agent

        result = Agent._build_thinking_config({})
        assert result["type"] == "adaptive"


# ---------------------------------------------------------------------------
# Tests: _disconnect_stale
# ---------------------------------------------------------------------------


class TestDisconnectStale:
    @pytest.mark.asyncio
    async def test_disconnect_stale_with_client(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        mock_client = _mock_sdk_client()

        with patch("smolclaw.agent.ClaudeSDKClient", return_value=mock_client):
            await agent.connect()

        await agent._disconnect_stale()
        assert agent._client is None
        assert agent.is_connected is False

    @pytest.mark.asyncio
    async def test_disconnect_stale_swallows_errors(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        mock_client = _mock_sdk_client()
        mock_client.disconnect = AsyncMock(side_effect=RuntimeError("already dead"))

        with patch("smolclaw.agent.ClaudeSDKClient", return_value=mock_client):
            await agent.connect()

        # Should not raise
        await agent._disconnect_stale()
        assert agent._client is None

    @pytest.mark.asyncio
    async def test_disconnect_stale_no_client(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info())
        # Should be a no-op
        await agent._disconnect_stale()
        assert agent._client is None


# ---------------------------------------------------------------------------
# Tests: __repr__
# ---------------------------------------------------------------------------


class TestAgentRepr:
    def test_repr(self):
        from smolclaw.agent import Agent

        agent = Agent(_make_info(name="tars", model="claude-opus-4-6"))
        r = repr(agent)
        assert "Agent" in r
        assert "tars" in r
        assert "claude-opus-4-6" in r
        assert "connected=False" in r
