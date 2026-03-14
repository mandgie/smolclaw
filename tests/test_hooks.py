"""Tests for the message hooks system."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from smolclaw.hooks import HookContext, HookRegistry
from smolclaw.router import InboundMessage, OutboundMessage, Router

# --- Fixtures ---


@pytest.fixture
def registry():
    return HookRegistry()


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.name = "testagent"
    agent.send = AsyncMock(return_value="Agent says hello")
    agent.memory = None
    return agent


@pytest.fixture
def router_with_hooks(mock_agent, registry):
    r = Router(hooks=registry)
    r.register_agent(mock_agent)
    return r


def _make_msg(text="Hi", agent="testagent", source="cli"):
    return InboundMessage(agent=agent, text=text, source=source)


# --- HookRegistry unit tests ---


class TestHookRegistryBasics:
    def test_repr_empty(self, registry):
        assert repr(registry) == "HookRegistry(pre=0, post=0)"

    def test_repr_with_hooks(self, registry):
        async def noop(msg, ctx):
            return None

        registry.add_pre_hook("a", noop)
        registry.add_post_hook("b", noop)
        assert repr(registry) == "HookRegistry(pre=1, post=1)"

    def test_add_pre_hook(self, registry):
        async def hook(msg, ctx):
            return None

        registry.add_pre_hook("my-hook", hook)
        assert "my-hook" in registry.pre_hook_names

    def test_add_post_hook(self, registry):
        async def hook(msg, response, ctx):
            return None

        registry.add_post_hook("my-hook", hook)
        assert "my-hook" in registry.post_hook_names

    def test_duplicate_pre_hook_raises(self, registry):
        async def hook(msg, ctx):
            return None

        registry.add_pre_hook("dup", hook)
        with pytest.raises(ValueError, match="already registered"):
            registry.add_pre_hook("dup", hook)

    def test_duplicate_post_hook_raises(self, registry):
        async def hook(msg, response, ctx):
            return None

        registry.add_post_hook("dup", hook)
        with pytest.raises(ValueError, match="already registered"):
            registry.add_post_hook("dup", hook)

    def test_remove_hook_pre(self, registry):
        async def hook(msg, ctx):
            return None

        registry.add_pre_hook("removeme", hook)
        assert registry.remove_hook("removeme") is True
        assert "removeme" not in registry.pre_hook_names

    def test_remove_hook_post(self, registry):
        async def hook(msg, response, ctx):
            return None

        registry.add_post_hook("removeme", hook)
        assert registry.remove_hook("removeme") is True
        assert "removeme" not in registry.post_hook_names

    def test_remove_nonexistent_hook(self, registry):
        assert registry.remove_hook("ghost") is False

    def test_clear(self, registry):
        async def hook(msg, ctx):
            return None

        registry.add_pre_hook("a", hook)
        registry.add_post_hook("b", hook)
        registry.clear()
        assert registry.pre_hook_names == []
        assert registry.post_hook_names == []

    def test_stats(self, registry):
        async def hook(msg, ctx):
            return None

        registry.add_pre_hook("pre1", hook)
        registry.add_pre_hook("pre2", hook)
        registry.add_post_hook("post1", hook)
        stats = registry.stats
        assert stats["pre_route"] == ["pre1", "pre2"]
        assert stats["post_route"] == ["post1"]
        assert stats["total"] == 3


# --- Pre-route hook execution ---


class TestPreRouteHooks:
    async def test_passthrough_returns_original(self, registry):
        """Hook returning None means pass through unchanged."""

        async def noop(msg, ctx):
            return None

        registry.add_pre_hook("noop", noop)
        msg = _make_msg("Hello")
        result = await registry.run_pre_hooks(msg)
        assert isinstance(result, InboundMessage)
        assert result.text == "Hello"

    async def test_modify_message(self, registry):
        """Hook can return a modified InboundMessage."""

        async def uppercaser(msg, ctx):
            return InboundMessage(agent=msg.agent, text=msg.text.upper(), source=msg.source)

        registry.add_pre_hook("upper", uppercaser)
        msg = _make_msg("hello")
        result = await registry.run_pre_hooks(msg)
        assert isinstance(result, InboundMessage)
        assert result.text == "HELLO"

    async def test_short_circuit(self, registry):
        """Hook returning OutboundMessage short-circuits routing."""

        async def blocker(msg, ctx):
            return OutboundMessage(agent=msg.agent, text="Blocked!", source=msg.source)

        registry.add_pre_hook("blocker", blocker)
        msg = _make_msg("bad request")
        result = await registry.run_pre_hooks(msg)
        assert isinstance(result, OutboundMessage)
        assert result.text == "Blocked!"

    async def test_chain_order(self, registry):
        """Multiple pre-hooks execute in registration order."""
        order = []

        async def first(msg, ctx):
            order.append("first")
            return InboundMessage(agent=msg.agent, text=msg.text + " [1]", source=msg.source)

        async def second(msg, ctx):
            order.append("second")
            return InboundMessage(agent=msg.agent, text=msg.text + " [2]", source=msg.source)

        registry.add_pre_hook("first", first)
        registry.add_pre_hook("second", second)
        msg = _make_msg("start")
        result = await registry.run_pre_hooks(msg)
        assert result.text == "start [1] [2]"
        assert order == ["first", "second"]

    async def test_short_circuit_stops_chain(self, registry):
        """When one hook short-circuits, later hooks don't execute."""
        executed = []

        async def blocker(msg, ctx):
            executed.append("blocker")
            return OutboundMessage(agent=msg.agent, text="Stopped", source=msg.source)

        async def never_reached(msg, ctx):
            executed.append("never")
            return None

        registry.add_pre_hook("blocker", blocker)
        registry.add_pre_hook("never", never_reached)
        msg = _make_msg()
        await registry.run_pre_hooks(msg)
        assert executed == ["blocker"]

    async def test_hook_error_continues_chain(self, registry):
        """A hook that raises doesn't stop later hooks."""
        executed = []

        async def crasher(msg, ctx):
            executed.append("crasher")
            raise RuntimeError("kaboom")

        async def survivor(msg, ctx):
            executed.append("survivor")
            return InboundMessage(agent=msg.agent, text="survived", source=msg.source)

        registry.add_pre_hook("crasher", crasher)
        registry.add_pre_hook("survivor", survivor)
        msg = _make_msg()
        result = await registry.run_pre_hooks(msg)
        assert executed == ["crasher", "survivor"]
        assert result.text == "survived"

    async def test_context_has_agent_and_source(self, registry):
        """HookContext is populated from the message."""
        captured_ctx = {}

        async def spy(msg, ctx):
            captured_ctx["agent"] = ctx.agent_name
            captured_ctx["source"] = ctx.source
            return None

        registry.add_pre_hook("spy", spy)
        msg = _make_msg(agent="tars", source="telegram")
        await registry.run_pre_hooks(msg)
        assert captured_ctx["agent"] == "tars"
        assert captured_ctx["source"] == "telegram"

    async def test_no_hooks_passthrough(self, registry):
        """With no hooks registered, message passes through unchanged."""
        msg = _make_msg("unchanged")
        result = await registry.run_pre_hooks(msg)
        assert result is msg


# --- Post-route hook execution ---


class TestPostRouteHooks:
    async def test_passthrough_returns_original(self, registry):
        """Hook returning None means pass through unchanged."""

        async def noop(msg, response, ctx):
            return None

        registry.add_post_hook("noop", noop)
        msg = _make_msg()
        resp = OutboundMessage(agent="testagent", text="response", source="cli")
        result = await registry.run_post_hooks(msg, resp)
        assert result.text == "response"

    async def test_modify_response(self, registry):
        """Hook can return a modified OutboundMessage."""

        async def add_footer(msg, response, ctx):
            return OutboundMessage(
                agent=response.agent,
                text=response.text + "\n-- footer",
                source=response.source,
            )

        registry.add_post_hook("footer", add_footer)
        msg = _make_msg()
        resp = OutboundMessage(agent="testagent", text="response", source="cli")
        result = await registry.run_post_hooks(msg, resp)
        assert result.text == "response\n-- footer"

    async def test_chain_order(self, registry):
        """Multiple post-hooks execute in registration order."""

        async def first(msg, response, ctx):
            return OutboundMessage(
                agent=response.agent,
                text=response.text + " [1]",
                source=response.source,
            )

        async def second(msg, response, ctx):
            return OutboundMessage(
                agent=response.agent,
                text=response.text + " [2]",
                source=response.source,
            )

        registry.add_post_hook("first", first)
        registry.add_post_hook("second", second)
        msg = _make_msg()
        resp = OutboundMessage(agent="testagent", text="base", source="cli")
        result = await registry.run_post_hooks(msg, resp)
        assert result.text == "base [1] [2]"

    async def test_hook_error_continues(self, registry):
        """A hook that raises doesn't stop later hooks."""

        async def crasher(msg, response, ctx):
            raise RuntimeError("kaboom")

        async def survivor(msg, response, ctx):
            return OutboundMessage(
                agent=response.agent,
                text="survived",
                source=response.source,
            )

        registry.add_post_hook("crasher", crasher)
        registry.add_post_hook("survivor", survivor)
        msg = _make_msg()
        resp = OutboundMessage(agent="testagent", text="original", source="cli")
        result = await registry.run_post_hooks(msg, resp)
        assert result.text == "survived"

    async def test_no_hooks_passthrough(self, registry):
        """With no hooks, response passes through unchanged."""
        msg = _make_msg()
        resp = OutboundMessage(agent="testagent", text="original", source="cli")
        result = await registry.run_post_hooks(msg, resp)
        assert result is resp


# --- Router integration with hooks ---


class TestRouterWithHooks:
    async def test_pre_hook_modifies_message(self, router_with_hooks, registry, mock_agent):
        """Pre-hook modifies the message before it reaches the agent."""

        async def prefix(msg, ctx):
            return InboundMessage(agent=msg.agent, text="[prefix] " + msg.text, source=msg.source)

        registry.add_pre_hook("prefix", prefix)
        msg = _make_msg("Hello")
        await router_with_hooks.route(msg)
        mock_agent.send.assert_awaited_once_with("[prefix] Hello")

    async def test_pre_hook_short_circuits(self, router_with_hooks, registry, mock_agent):
        """Pre-hook short-circuiting prevents agent from being called."""

        async def blocker(msg, ctx):
            return OutboundMessage(agent=msg.agent, text="Blocked", source=msg.source)

        registry.add_pre_hook("blocker", blocker)
        msg = _make_msg("Hello")
        result = await router_with_hooks.route(msg)
        assert result.text == "Blocked"
        mock_agent.send.assert_not_awaited()

    async def test_post_hook_modifies_response(self, router_with_hooks, registry, mock_agent):
        """Post-hook modifies the agent's response."""

        async def censor(msg, response, ctx):
            return OutboundMessage(
                agent=response.agent,
                text=response.text.replace("hello", "***"),
                source=response.source,
            )

        registry.add_post_hook("censor", censor)
        msg = _make_msg("Hello")
        result = await router_with_hooks.route(msg)
        assert result.text == "Agent says ***"

    async def test_pre_and_post_hooks_both_run(self, router_with_hooks, registry, mock_agent):
        """Both pre and post hooks execute in a single route."""
        order = []

        async def pre(msg, ctx):
            order.append("pre")
            return None

        async def post(msg, response, ctx):
            order.append("post")
            return None

        registry.add_pre_hook("pre", pre)
        registry.add_post_hook("post", post)
        msg = _make_msg()
        await router_with_hooks.route(msg)
        assert order == ["pre", "post"]

    async def test_router_without_hooks(self, mock_agent):
        """Router works fine with no hooks registered."""
        r = Router()
        r.register_agent(mock_agent)
        msg = _make_msg()
        result = await r.route(msg)
        assert result.text == "Agent says hello"

    async def test_router_hooks_property(self, registry):
        r = Router(hooks=registry)
        assert r.hooks is registry

    async def test_router_hooks_setter(self):
        r = Router()
        assert r.hooks is None
        reg = HookRegistry()
        r.hooks = reg
        assert r.hooks is reg

    async def test_pre_hook_redirect_to_different_agent(
        self, router_with_hooks, registry, mock_agent
    ):
        """Pre-hook can redirect a message to a different agent."""
        other_agent = MagicMock()
        other_agent.name = "other"
        other_agent.send = AsyncMock(return_value="Other agent response")
        other_agent.memory = None
        router_with_hooks.register_agent(other_agent)

        async def redirect(msg, ctx):
            return InboundMessage(agent="other", text=msg.text, source=msg.source)

        registry.add_pre_hook("redirect", redirect)
        msg = _make_msg(agent="testagent")
        result = await router_with_hooks.route(msg)
        assert result.text == "Other agent response"
        mock_agent.send.assert_not_awaited()
        other_agent.send.assert_awaited_once()


# --- HookContext ---


class TestHookContext:
    def test_defaults(self):
        ctx = HookContext(agent_name="tars")
        assert ctx.agent_name == "tars"
        assert ctx.source == ""
        assert ctx.metadata == {}

    def test_metadata_isolation(self):
        ctx1 = HookContext(agent_name="a")
        ctx2 = HookContext(agent_name="b")
        ctx1.metadata["key"] = "val"
        assert "key" not in ctx2.metadata
