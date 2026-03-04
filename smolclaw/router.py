"""Message routing — any source → correct agent → response delivery."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent import Agent

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
    """Routes messages to agents and collects responses."""

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}
        self._handlers: dict[str, list[Callable[[OutboundMessage], Awaitable[None]]]] = {}

    def register_agent(self, agent: Agent) -> None:
        self._agents[agent.name] = agent
        log.info(f"Router: registered agent '{agent.name}'")

    def on_response(
        self, source: str, callback: Callable[[OutboundMessage], Awaitable[None]]
    ) -> None:
        """Register a callback for outbound messages from a source."""
        self._handlers.setdefault(source, []).append(callback)

    async def route(self, message: InboundMessage) -> OutboundMessage:
        """Route an inbound message to the correct agent, return response."""
        agent = self._agents.get(message.agent)
        if not agent:
            log.error(f"Router: no agent '{message.agent}' registered")
            return OutboundMessage(
                agent=message.agent,
                text=f"Agent '{message.agent}' not found.",
                source=message.source,
                chat_id=message.chat_id,
            )

        try:
            response_text = await agent.send(message.text)
        except Exception as e:
            log.error(f"Router: agent '{message.agent}' error: {e}")
            response_text = f"Error: {e}"

        outbound = OutboundMessage(
            agent=message.agent,
            text=response_text,
            source=message.source,
            chat_id=message.chat_id,
        )

        # Notify handlers for this source
        for callback in self._handlers.get(message.source, []):
            try:
                await callback(outbound)
            except Exception as e:
                log.error(f"Router: handler error for source '{message.source}': {e}")

        return outbound

    def get_agent(self, name: str) -> Agent | None:
        return self._agents.get(name)

    @property
    def agents(self) -> dict[str, Agent]:
        return dict(self._agents)
