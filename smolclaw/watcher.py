"""Hot-reload watcher — monitors agent directories for config/skill/context changes."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Coroutine

if TYPE_CHECKING:
    from .config import AgentInfo

log = logging.getLogger("smolclaw")

__all__ = ["FileWatcher", "WATCHFILES_AVAILABLE"]

# watchfiles is an optional dependency — degrade gracefully if missing
try:
    from watchfiles import Change, awatch

    WATCHFILES_AVAILABLE = True
except ImportError:
    WATCHFILES_AVAILABLE = False

# File patterns that trigger a reload
_WATCHED_SUFFIXES = {".yaml", ".yml", ".md"}
_WATCHED_NAMES = {"SKILL.md", "agent.yaml", "soul.md", "agents.md"}

ReloadCallback = Callable[[str, "AgentInfo"], Coroutine]


def _is_watched_file(path: Path) -> bool:
    """Return True if this file change should trigger a reload."""
    if path.name in _WATCHED_NAMES:
        return True
    if path.suffix in _WATCHED_SUFFIXES:
        # Context files, skill files, or any .md/.yaml in agent tree
        return True
    return False


def _agent_name_from_path(path: Path, agents_dir: Path) -> str | None:
    """Extract agent name from a changed file path.

    Given agents_dir=/home/.smolclaw/agents and path=.../agents/tars/soul.md,
    returns "tars".
    """
    try:
        rel = path.relative_to(agents_dir)
        return rel.parts[0] if rel.parts else None
    except ValueError:
        return None


class FileWatcher:
    """Watches agent directories for file changes and triggers reload callbacks."""

    def __init__(
        self,
        agents_dir: Path,
        on_reload: ReloadCallback,
        debounce_ms: int = 500,
    ):
        self.agents_dir = agents_dir
        self.on_reload = on_reload
        self.debounce_ms = debounce_ms
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start watching for file changes in the background."""
        if not WATCHFILES_AVAILABLE:
            log.warning("watchfiles not installed — hot-reload disabled (pip install watchfiles)")
            return

        if not self.agents_dir.exists():
            log.warning(f"Agents directory {self.agents_dir} not found — watcher not started")
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._watch_loop())
        log.info(f"File watcher started on {self.agents_dir}")

    async def stop(self) -> None:
        """Stop the file watcher."""
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("File watcher stopped")

    async def _watch_loop(self) -> None:
        """Main watch loop — debounces changes and calls reload callback per agent."""
        try:
            async for changes in awatch(
                self.agents_dir,
                debounce=self.debounce_ms,
                stop_event=self._stop_event,
                recursive=True,
            ):
                await self._handle_changes(changes)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error(f"File watcher error: {e}")

    async def _handle_changes(self, changes: set[tuple[Change, str]]) -> None:
        """Process a batch of file changes, reload affected agents."""
        from .config import discover_agent  # noqa: F811 — deferred to avoid circular

        agents_to_reload: dict[str, list[str]] = {}

        for _change_type, path_str in changes:
            path = Path(path_str)
            if not _is_watched_file(path):
                continue

            agent_name = _agent_name_from_path(path, self.agents_dir)
            if agent_name is None:
                continue

            if agent_name not in agents_to_reload:
                agents_to_reload[agent_name] = []
            agents_to_reload[agent_name].append(path.name)

        for agent_name, changed_files in agents_to_reload.items():
            agent_dir = self.agents_dir / agent_name
            if not (agent_dir / "agent.yaml").exists():
                log.warning(f"[watcher] {agent_name}: agent.yaml missing, skipping reload")
                continue

            try:
                new_info = discover_agent(agent_dir)
                log.info(
                    f"[watcher] Reloading {agent_name} "
                    f"(changed: {', '.join(sorted(set(changed_files)))})"
                )
                await self.on_reload(agent_name, new_info)
            except Exception as e:
                log.error(f"[watcher] Failed to reload {agent_name}: {e}")
