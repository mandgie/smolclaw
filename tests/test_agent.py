"""Tests for smolclaw.agent — Agent class with mocked Claude SDK."""

from __future__ import annotations

import asyncio
from pathlib import Path
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
