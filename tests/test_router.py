"""Tests for the message Router."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from smolclaw.router import InboundMessage, OutboundMessage, Router


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.name = "testagent"
    agent.send = AsyncMock(return_value="Hello back!")
    return agent


@pytest.fixture
def router(mock_agent):
    r = Router()
    r.register_agent(mock_agent)
    return r


class TestRouter:
    async def test_register_and_get_agent(self, router, mock_agent):
        assert router.get_agent("testagent") is mock_agent
        assert router.get_agent("nonexistent") is None

    async def test_agents_property(self, router):
        agents = router.agents
        assert "testagent" in agents

    async def test_route_success(self, router, mock_agent):
        msg = InboundMessage(agent="testagent", text="Hello", source="cli")
        result = await router.route(msg)

        assert isinstance(result, OutboundMessage)
        assert result.text == "Hello back!"
        assert result.agent == "testagent"
        assert result.source == "cli"
        mock_agent.send.assert_awaited_once_with("Hello")

    async def test_route_unknown_agent(self, router):
        msg = InboundMessage(agent="ghost", text="Hello", source="cli")
        result = await router.route(msg)
        assert "not found" in result.text.lower()

    async def test_route_agent_error(self, router, mock_agent):
        mock_agent.send = AsyncMock(side_effect=RuntimeError("SDK crashed"))
        msg = InboundMessage(agent="testagent", text="Hello", source="cli")
        result = await router.route(msg)
        assert "Error" in result.text

    async def test_route_calls_handlers(self, router, mock_agent):
        callback = AsyncMock()
        router.on_response("cli", callback)

        msg = InboundMessage(agent="testagent", text="Hello", source="cli")
        await router.route(msg)

        callback.assert_awaited_once()
        outbound = callback.call_args[0][0]
        assert outbound.text == "Hello back!"

    async def test_handler_error_doesnt_break_routing(self, router, mock_agent):
        bad_callback = AsyncMock(side_effect=RuntimeError("Handler broke"))
        router.on_response("cli", bad_callback)

        msg = InboundMessage(agent="testagent", text="Hello", source="cli")
        result = await router.route(msg)
        assert result.text == "Hello back!"


class TestInboundMessage:
    def test_defaults(self):
        msg = InboundMessage(agent="a", text="t", source="cli")
        assert msg.chat_id == ""
        assert msg.session_key == ""
        assert msg.timestamp is not None
