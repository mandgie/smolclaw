"""Message routing — any source → correct agent → response delivery."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent import Agent
    from .hooks import HookRegistry

log = logging.getLogger("smolclaw")

__all__ = ["InboundMessage", "OutboundMessage", "Router"]


@dataclass
class InboundMessage:
    """A message from any source, normalized."""

    agent: str
    text: str
    source: str  # "telegram", "cli", "cron", "api"
    chat_id: str = ""
    session_key: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class OutboundMessage:
    """A response to be delivered."""

    agent: str
    text: str
    source: str
    chat_id: str = ""


class Router:
    """Routes messages to agents and collects responses.

    Supports pre-route and post-route hooks via a HookRegistry. Hooks are
    executed in order before and after agent invocation, allowing message
    transformation, short-circuiting, rate limiting, logging, etc.
    """

    def __init__(self, hooks: HookRegistry | None = None) -> None:
        """Initialize the router with empty agent and handler registries.

        Args:
            hooks: Optional hook registry for pre/post-route message hooks.
        """
        self._agents: dict[str, Agent] = {}
        self._handlers: dict[str, list[Callable[[OutboundMessage], Awaitable[None]]]] = {}
        self._hooks: HookRegistry | None = hooks

    def __repr__(self) -> str:
        names = list(self._agents.keys())
        return f"Router(agents={names})"

    def register_agent(self, agent: Agent) -> None:
        """Register an agent so it can receive routed messages."""
        self._agents[agent.name] = agent
        log.info(f"Router: registered agent '{agent.name}'")

    def on_response(
        self, source: str, callback: Callable[[OutboundMessage], Awaitable[None]]
    ) -> None:
        """Register a callback for outbound messages from a source."""
        self._handlers.setdefault(source, []).append(callback)

    @property
    def hooks(self) -> HookRegistry | None:
        """The hook registry attached to this router, if any."""
        return self._hooks

    @hooks.setter
    def hooks(self, registry: HookRegistry | None) -> None:
        self._hooks = registry

    async def route(self, message: InboundMessage) -> OutboundMessage:
        """Route an inbound message to the correct agent, return response.

        If hooks are registered, pre-route hooks execute first (may modify the
        message or short-circuit). After the agent responds, post-route hooks
        execute (may modify the response).
        """
        from .tracing import set_span_attribute, trace_route

        with trace_route(message.agent, message.source, message.text):
            # --- Pre-route hooks ---
            routed_message = message
            if self._hooks:
                result = await self._hooks.run_pre_hooks(message)
                if isinstance(result, OutboundMessage):
                    # Hook short-circuited — skip agent, deliver directly
                    set_span_attribute("smolclaw.hooks.short_circuited", True)
                    return result
                routed_message = result

            agent = self._agents.get(routed_message.agent)
            if not agent:
                log.error(f"Router: no agent '{routed_message.agent}' registered")
                return OutboundMessage(
                    agent=routed_message.agent,
                    text=f"Agent '{routed_message.agent}' not found.",
                    source=routed_message.source,
                    chat_id=routed_message.chat_id,
                )

            try:
                response_text = await agent.send(routed_message.text)
            except Exception as e:
                log.error(f"Router: agent '{routed_message.agent}' error: {e}")
                response_text = f"Error: {e}"

            # Auto-save conversation chunk to memory (non-blocking)
            if agent.memory and not response_text.startswith("Error:"):
                try:
                    session_id = getattr(agent, "_session_id", "") or ""
                    agent.memory.add_chunk(
                        user_text=routed_message.text,
                        assistant_text=response_text[:2000],
                        session_id=session_id,
                    )
                except Exception as e:
                    log.warning(f"Router: memory save failed for '{routed_message.agent}': {e}")

            outbound = OutboundMessage(
                agent=routed_message.agent,
                text=response_text,
                source=routed_message.source,
                chat_id=routed_message.chat_id,
            )

            # --- Post-route hooks ---
            if self._hooks:
                outbound = await self._hooks.run_post_hooks(routed_message, outbound)

            set_span_attribute("smolclaw.response.length", len(outbound.text))

            # Notify handlers for this source
            for callback in self._handlers.get(routed_message.source, []):
                try:
                    await callback(outbound)
                except Exception as e:
                    log.error(f"Router: handler error for source '{routed_message.source}': {e}")

            return outbound

    def get_agent(self, name: str) -> Agent | None:
        """Look up a registered agent by name, or None if not found."""
        return self._agents.get(name)

    @property
    def agents(self) -> dict[str, Agent]:
        """Return a copy of the registered agents dict."""
        return dict(self._agents)
