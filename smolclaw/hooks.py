"""Message-level hooks — intercept and transform messages before/after routing."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .router import InboundMessage, OutboundMessage

log = logging.getLogger("smolclaw")

__all__ = [
    "HookContext",
    "HookRegistry",
    "PostRouteHook",
    "PreRouteHook",
]


# --- Hook type aliases ---

# Pre-route hook signature:
#   async (message, ctx) -> InboundMessage | OutboundMessage | None
#   - InboundMessage: modified message (continue routing)
#   - OutboundMessage: short-circuit (skip agent, return response directly)
#   - None: pass through unchanged
PreRouteHook = Callable[
    ["InboundMessage", "HookContext"],
    Awaitable[InboundMessage | OutboundMessage | None],
]

# Post-route hook signature:
#   async (message, response, ctx) -> OutboundMessage | None
#   - OutboundMessage: modified response
#   - None: pass through unchanged
PostRouteHook = Callable[
    ["InboundMessage", "OutboundMessage", "HookContext"],
    Awaitable[OutboundMessage | None],
]


@dataclass
class HookContext:
    """Context passed to every hook invocation.

    Attributes:
        agent_name: Name of the target agent.
        source: Message source (telegram, cli, api, cron).
        metadata: Arbitrary key-value data hooks can read/write to share state.
    """

    agent_name: str
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class HookRegistry:
    """Registry of pre-route and post-route message hooks.

    Hooks execute in registration order. Pre-route hooks can modify the inbound
    message or short-circuit routing entirely. Post-route hooks can modify the
    outbound response.

    Example::

        registry = HookRegistry()

        async def log_messages(msg, ctx):
            print(f"[{ctx.agent_name}] {msg.text}")
            return None  # pass through

        registry.add_pre_hook("logger", log_messages)
    """

    def __init__(self) -> None:
        self._pre: list[tuple[str, PreRouteHook]] = []
        self._post: list[tuple[str, PostRouteHook]] = []

    def __repr__(self) -> str:
        return f"HookRegistry(pre={len(self._pre)}, post={len(self._post)})"

    def add_pre_hook(self, name: str, hook: PreRouteHook) -> None:
        """Register a pre-route hook.

        Args:
            name: Unique identifier for this hook (used for removal/debugging).
            hook: Async callable matching the PreRouteHook signature.
        """
        if any(n == name for n, _ in self._pre):
            raise ValueError(f"Pre-route hook '{name}' already registered")
        self._pre.append((name, hook))
        log.info(f"Hooks: registered pre-route '{name}'")

    def add_post_hook(self, name: str, hook: PostRouteHook) -> None:
        """Register a post-route hook.

        Args:
            name: Unique identifier for this hook (used for removal/debugging).
            hook: Async callable matching the PostRouteHook signature.
        """
        if any(n == name for n, _ in self._post):
            raise ValueError(f"Post-route hook '{name}' already registered")
        self._post.append((name, hook))
        log.info(f"Hooks: registered post-route '{name}'")

    def remove_hook(self, name: str) -> bool:
        """Remove a hook by name from both pre and post registries.

        Returns:
            True if a hook was found and removed, False otherwise.
        """
        before = len(self._pre) + len(self._post)
        self._pre = [(n, h) for n, h in self._pre if n != name]
        self._post = [(n, h) for n, h in self._post if n != name]
        after = len(self._pre) + len(self._post)
        removed = after < before
        if removed:
            log.info(f"Hooks: removed '{name}'")
        return removed

    def clear(self) -> None:
        """Remove all hooks."""
        self._pre.clear()
        self._post.clear()
        log.info("Hooks: cleared all hooks")

    async def run_pre_hooks(self, message: InboundMessage) -> InboundMessage | OutboundMessage:
        """Execute all pre-route hooks in registration order.

        Args:
            message: The inbound message about to be routed.

        Returns:
            InboundMessage (possibly modified) if routing should continue,
            or OutboundMessage if a hook short-circuited routing.
        """
        ctx = HookContext(agent_name=message.agent, source=message.source)
        current: InboundMessage = message

        for name, hook in self._pre:
            try:
                result = await hook(current, ctx)
                if isinstance(result, OutboundMessage):
                    log.info(f"Hook '{name}' short-circuited routing for '{message.agent}'")
                    return result
                if isinstance(result, InboundMessage):
                    current = result
                # None means pass through unchanged
            except Exception as e:
                log.error(f"Pre-route hook '{name}' failed: {e}")

        return current

    async def run_post_hooks(
        self, message: InboundMessage, response: OutboundMessage
    ) -> OutboundMessage:
        """Execute all post-route hooks in registration order.

        Args:
            message: The original inbound message.
            response: The outbound response from the agent.

        Returns:
            OutboundMessage, possibly modified by hooks.
        """
        ctx = HookContext(agent_name=message.agent, source=message.source)
        current: OutboundMessage = response

        for name, hook in self._post:
            try:
                result = await hook(message, current, ctx)
                if isinstance(result, OutboundMessage):
                    current = result
            except Exception as e:
                log.error(f"Post-route hook '{name}' failed: {e}")

        return current

    @property
    def pre_hook_names(self) -> list[str]:
        """List registered pre-route hook names in execution order."""
        return [name for name, _ in self._pre]

    @property
    def post_hook_names(self) -> list[str]:
        """List registered post-route hook names in execution order."""
        return [name for name, _ in self._post]

    @property
    def stats(self) -> dict[str, Any]:
        """Summary of registered hooks."""
        return {
            "pre_route": self.pre_hook_names,
            "post_route": self.post_hook_names,
            "total": len(self._pre) + len(self._post),
        }
