"""Core Agent class — identity loading, system prompt building, Claude SDK interaction."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Any

# Strip nested session detection so SDK works from inside Claude Code / cron / etc.
os.environ.pop("CLAUDECODE", None)

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    CLIConnectionError,
    ResultMessage,
    TaskNotificationMessage,
    TaskProgressMessage,
    TaskStartedMessage,
    TextBlock,
)
from claude_agent_sdk.types import (
    StreamEvent,
    ThinkingConfigAdaptive,
    ThinkingConfigDisabled,
    ThinkingConfigEnabled,
)

from .config import AgentInfo
from .memory import Memory

log = logging.getLogger("smolclaw")

__all__ = ["Agent"]


class Agent:
    """A named AI agent with its own identity, skills, and Claude SDK session."""

    def __init__(self, info: AgentInfo, user_md: str = ""):
        """Initialize an agent from its discovered filesystem info.

        Args:
            info: Agent identity, config, skills, and context loaded from disk.
            user_md: Shared USER.md content injected into the system prompt.
        """
        self.info = info
        self.name = info.config.name
        self.model = info.config.model
        self.user_md = user_md

        self.memory: Memory | None = None
        self.peers: list[dict[str, str]] = []  # [{name, model, description}]
        self.gateway_url: str = "http://localhost:7890"

        self._client: ClaudeSDKClient | None = None
        self._connected = False
        self._session_id: str | None = None
        self._lock = asyncio.Lock()

        # Last query metadata (updated after each send)
        self.last_cost_usd: float | None = None
        self.last_usage: dict[str, Any] | None = None
        self.last_structured_output: Any = None
        self.last_num_turns: int | None = None
        self.last_duration_ms: int | None = None
        self.last_duration_api_ms: int | None = None
        self.last_stop_reason: str | None = None

    def __repr__(self) -> str:
        return f"Agent(name={self.name!r}, model={self.model!r}, connected={self._connected})"

    @property
    def is_connected(self) -> bool:
        """Whether this agent has an active Claude SDK connection."""
        return self._connected

    def build_system_prompt(self) -> str:
        """Assemble the system prompt from agent files."""
        parts: list[str] = []

        # Shared user context
        if self.user_md:
            parts.append(self.user_md)

        # Agent identity
        if self.info.soul:
            parts.append(self.info.soul)

        # Operational rules
        if self.info.agents_md:
            parts.append(self.info.agents_md)

        # Skills
        for skill in self.info.skills:
            parts.append(skill)

        # Context files
        for name, content in self.info.context_files.items():
            parts.append(f"--- {name} ---\n{content}")

        # Peer agents (cross-agent awareness)
        if self.peers:
            peer_lines = ["--- Peer Agents ---"]
            peer_lines.append(
                "Other agents are running in this gateway. "
                "You can send them messages via the local API:"
            )
            peer_lines.append(
                f"  curl -s -X POST {self.gateway_url}/api/agents/<name>/send "
                '-H "Content-Type: application/json" '
                '-d \'{"text": "your message"}\' | jq -r .response'
            )
            peer_lines.append("")
            for peer in self.peers:
                desc = f" — {peer['description']}" if peer.get("description") else ""
                peer_lines.append(f"- **{peer['name']}** ({peer['model']}){desc}")
            parts.append("\n".join(peer_lines))

        # Runtime context
        today = datetime.now().strftime("%Y-%m-%d (%A)")
        parts.append(
            f"--- Runtime ---\n"
            f"Today: {today}\n"
            f"Agent: {self.name}\n"
            f"Model: {self.model}\n"
            f"Workspace: {self.info.path}"
        )

        return "\n\n".join(parts)

    @staticmethod
    def _build_thinking_config(
        cfg: dict[str, Any],
    ) -> ThinkingConfigAdaptive | ThinkingConfigEnabled | ThinkingConfigDisabled | None:
        """Convert a thinking config dict to the appropriate SDK type."""
        thinking_type = cfg.get("type", "adaptive")
        if thinking_type == "enabled":
            return ThinkingConfigEnabled(type="enabled", budget_tokens=cfg.get("budget_tokens", 0))
        if thinking_type == "disabled":
            return ThinkingConfigDisabled(type="disabled")
        return ThinkingConfigAdaptive(type="adaptive")

    def _make_options(self, resume_id: str | None = None) -> ClaudeAgentOptions:
        opts = ClaudeAgentOptions(
            model=self.model,
            cwd=str(self.info.path),
            permission_mode="bypassPermissions",
            system_prompt=self.build_system_prompt(),
            setting_sources=["user", "project"],
        )
        cfg = self.info.config
        if cfg.max_turns is not None:
            opts.max_turns = cfg.max_turns
        if cfg.max_budget_usd is not None:
            opts.max_budget_usd = cfg.max_budget_usd
        if cfg.fallback_model is not None:
            opts.fallback_model = cfg.fallback_model
        if cfg.output_format is not None:
            opts.output_format = cfg.output_format
        if cfg.enable_file_checkpointing:
            opts.enable_file_checkpointing = True
        if cfg.mcp_servers is not None:
            if isinstance(cfg.mcp_servers, str):
                # Path to mcp.json — resolve relative to agent dir
                mcp_path = self.info.path / cfg.mcp_servers
                opts.mcp_servers = str(mcp_path) if mcp_path.exists() else cfg.mcp_servers
            else:
                opts.mcp_servers = cfg.mcp_servers
        if cfg.thinking is not None:
            opts.thinking = self._build_thinking_config(cfg.thinking)
        if cfg.effort is not None:
            opts.effort = cfg.effort
        if cfg.betas:
            opts.betas = cfg.betas
        if cfg.add_dirs:
            opts.add_dirs = [str(self.info.path / d) for d in cfg.add_dirs]
        if resume_id:
            opts.resume = resume_id
        return opts

    async def connect(self, resume_id: str | None = None) -> bool:
        """Connect to Claude SDK. Returns True if successful."""
        if self._client and self._connected:
            return True

        await self._disconnect_stale()

        try:
            opts = self._make_options(resume_id=resume_id)
            self._client = ClaudeSDKClient(options=opts)
            await self._client.connect()
            self._connected = True
            log.info(f"[{self.name}] Connected (resume={resume_id or 'new'})")
            return True
        except CLIConnectionError:
            if resume_id:
                log.info(f"[{self.name}] Resume failed, trying fresh session")
                return await self.connect(resume_id=None)
            log.error(f"[{self.name}] Failed to connect")
            return False
        except Exception as e:
            log.error(f"[{self.name}] Connection error: {e}")
            self._client = None
            self._connected = False
            return False

    async def _disconnect_stale(self) -> None:
        if self._client:
            try:
                await self._client.disconnect()
            except Exception as e:
                log.debug(f"[{self.name}] Disconnect error (ignored): {e}")
            self._client = None
            self._connected = False

    async def send(self, text: str) -> str:
        """Send a message and return the response. Thread-safe per agent."""
        async with self._lock:
            return await self._send_internal(text)

    async def _send_internal(self, text: str) -> str:
        from .tracing import set_span_attribute, trace_llm_call

        if not await self.connect(resume_id=self._session_id):
            raise CLIConnectionError(f"[{self.name}] Could not connect")

        log.info(f"[{self.name}] Query: {text[:80]}{'...' if len(text) > 80 else ''}")
        start = time.time()
        response_parts: list[str] = []
        self.last_structured_output = None

        with trace_llm_call(self.name, self.model, text):
            try:
                await self._client.query(text)
                async for message in self._client.receive_response():
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                response_parts.append(block.text)
                    elif isinstance(message, ResultMessage):
                        self._session_id = message.session_id
                        self.last_cost_usd = message.total_cost_usd
                        self.last_usage = message.usage
                        self.last_num_turns = message.num_turns
                        self.last_duration_ms = message.duration_ms
                        self.last_duration_api_ms = message.duration_api_ms
                        self.last_stop_reason = message.stop_reason
                        if message.structured_output is not None:
                            self.last_structured_output = message.structured_output
                        if message.is_error and message.result:
                            response_parts.append(f"[Error: {message.result}]")
                    elif isinstance(message, TaskStartedMessage):
                        log.debug(f"[{self.name}] Task started: {message.description}")
                    elif isinstance(message, TaskProgressMessage):
                        log.debug(
                            f"[{self.name}] Task progress: {message.description}"
                            f" (tokens={message.usage.total_tokens})"
                        )
                    elif isinstance(message, TaskNotificationMessage):
                        log.debug(f"[{self.name}] Task {message.status}: {message.summary}")
                    elif isinstance(message, StreamEvent):
                        log.debug(f"[{self.name}] Stream event: {message.event}")
            except Exception as e:
                log.error(f"[{self.name}] Query failed ({time.time() - start:.1f}s): {e}")
                self._connected = False
                raise

            # If structured output was returned, serialize it as the response
            if self.last_structured_output is not None:
                response = json.dumps(self.last_structured_output, indent=2)
            else:
                response = "\n".join(response_parts) if response_parts else "(No response)"

            elapsed = time.time() - start
            cost_str = f", ${self.last_cost_usd:.4f}" if self.last_cost_usd else ""
            log.info(f"[{self.name}] Response ({elapsed:.1f}s, {len(response)} chars{cost_str})")

            # Record LLM response metadata on the span (GenAI conventions)
            set_span_attribute("gen_ai.response.model", self.model)
            set_span_attribute("smolclaw.response.length", len(response))
            if self.last_cost_usd is not None:
                set_span_attribute("smolclaw.cost_usd", self.last_cost_usd)
            if self.last_num_turns is not None:
                set_span_attribute("smolclaw.usage.turns", self.last_num_turns)
            if self.last_duration_ms is not None:
                set_span_attribute("smolclaw.duration_ms", self.last_duration_ms)
            if self.last_stop_reason:
                set_span_attribute("gen_ai.response.finish_reasons", [self.last_stop_reason])
            if self.last_usage:
                if hasattr(self.last_usage, "input_tokens"):
                    set_span_attribute("gen_ai.usage.input_tokens", self.last_usage.input_tokens)
                if hasattr(self.last_usage, "output_tokens"):
                    set_span_attribute("gen_ai.usage.output_tokens", self.last_usage.output_tokens)

            if self.last_stop_reason == "max_tokens":
                log.warning(
                    f"[{self.name}] Response truncated (stop_reason=max_tokens)."
                    " Consider increasing max_turns or simplifying the query."
                )
            return response

    async def new_session(self) -> None:
        """Drop current session and start fresh."""
        await self._disconnect_stale()
        self._session_id = None
        log.info(f"[{self.name}] Session cleared")

    async def shutdown(self) -> None:
        """Clean shutdown."""
        await self._disconnect_stale()
        log.info(f"[{self.name}] Shut down")
