"""Core Agent class — identity loading, system prompt building, Claude SDK interaction."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime

# Strip nested session detection so SDK works from inside Claude Code / cron / etc.
os.environ.pop("CLAUDECODE", None)

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    CLIConnectionError,
    ResultMessage,
    TextBlock,
)

from .config import AgentInfo
from .memory import Memory

log = logging.getLogger("smolclaw")


class Agent:
    """A named AI agent with its own identity, skills, and Claude SDK session."""

    def __init__(self, info: AgentInfo, user_md: str = ""):
        self.info = info
        self.name = info.config.name
        self.model = info.config.model
        self.user_md = user_md

        self.memory: Memory | None = None

        self._client: ClaudeSDKClient | None = None
        self._connected = False
        self._session_id: str | None = None
        self._lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
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

    def _make_options(self, resume_id: str | None = None) -> ClaudeAgentOptions:
        opts = ClaudeAgentOptions(
            model=self.model,
            cwd=str(self.info.path),
            permission_mode="bypassPermissions",
            system_prompt=self.build_system_prompt(),
            setting_sources=["user", "project"],
        )
        if self.info.config.max_turns is not None:
            opts.max_turns = self.info.config.max_turns
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
            except Exception:
                pass
            self._client = None
            self._connected = False

    async def send(self, text: str, session_key: str | None = None) -> str:
        """Send a message and return the response. Thread-safe per agent."""
        async with self._lock:
            return await self._send_internal(text)

    async def _send_internal(self, text: str) -> str:
        if not await self.connect(resume_id=self._session_id):
            raise CLIConnectionError(f"[{self.name}] Could not connect")

        log.info(f"[{self.name}] Query: {text[:80]}{'...' if len(text) > 80 else ''}")
        start = time.time()
        response_parts: list[str] = []

        try:
            await self._client.query(text)
            async for message in self._client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            response_parts.append(block.text)
                elif isinstance(message, ResultMessage):
                    self._session_id = message.session_id
                    if message.is_error and message.result:
                        response_parts.append(f"[Error: {message.result}]")
        except Exception as e:
            log.error(f"[{self.name}] Query failed ({time.time() - start:.1f}s): {e}")
            self._connected = False
            raise

        response = "\n".join(response_parts) if response_parts else "(No response)"
        log.info(f"[{self.name}] Response ({time.time() - start:.1f}s, {len(response)} chars)")
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
