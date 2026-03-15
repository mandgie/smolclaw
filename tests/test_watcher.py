"""Tests for smolclaw.watcher — FileWatcher and hot-reload logic."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from smolclaw.watcher import (
    FileWatcher,
    _agent_name_from_path,
    _is_watched_file,
)

# ---------------------------------------------------------------------------
# Tests: _is_watched_file
# ---------------------------------------------------------------------------


class TestIsWatchedFile:
    def test_agent_yaml(self):
        assert _is_watched_file(Path("agents/tars/agent.yaml")) is True

    def test_soul_md(self):
        assert _is_watched_file(Path("agents/tars/soul.md")) is True

    def test_agents_md(self):
        assert _is_watched_file(Path("agents/tars/agents.md")) is True

    def test_skill_md(self):
        assert _is_watched_file(Path("agents/tars/skills/remindctl/SKILL.md")) is True

    def test_context_md(self):
        assert _is_watched_file(Path("agents/tars/context/SALTFISH.md")) is True

    def test_yaml_file(self):
        assert _is_watched_file(Path("agents/tars/some.yml")) is True

    def test_python_file_ignored(self):
        assert _is_watched_file(Path("agents/tars/script.py")) is False

    def test_json_file_ignored(self):
        assert _is_watched_file(Path("agents/tars/data.json")) is False

    def test_env_file_ignored(self):
        assert _is_watched_file(Path("agents/tars/channels/bot.env")) is False

    def test_binary_file_ignored(self):
        assert _is_watched_file(Path("agents/tars/image.png")) is False


# ---------------------------------------------------------------------------
# Tests: _agent_name_from_path
# ---------------------------------------------------------------------------


class TestAgentNameFromPath:
    def test_extracts_agent_name(self):
        agents = Path("/home/.smolclaw/agents")
        changed = Path("/home/.smolclaw/agents/tars/soul.md")
        assert _agent_name_from_path(changed, agents) == "tars"

    def test_nested_skill_file(self):
        agents = Path("/home/.smolclaw/agents")
        changed = Path("/home/.smolclaw/agents/coach/skills/timer/SKILL.md")
        assert _agent_name_from_path(changed, agents) == "coach"

    def test_unrelated_path_returns_none(self):
        agents = Path("/home/.smolclaw/agents")
        changed = Path("/home/.smolclaw/shared/USER.md")
        assert _agent_name_from_path(changed, agents) is None

    def test_agents_dir_itself_returns_none(self):
        agents = Path("/home/.smolclaw/agents")
        assert _agent_name_from_path(agents, agents) is None


# ---------------------------------------------------------------------------
# Tests: FileWatcher.__init__
# ---------------------------------------------------------------------------


class TestFileWatcherInit:
    def test_basic_init(self, tmp_path: Path):
        cb = AsyncMock()
        fw = FileWatcher(tmp_path, cb)
        assert fw.agents_dir == tmp_path
        assert fw.on_reload is cb
        assert fw.debounce_ms == 500
        assert fw._task is None

    def test_custom_debounce(self, tmp_path: Path):
        fw = FileWatcher(tmp_path, AsyncMock(), debounce_ms=1000)
        assert fw.debounce_ms == 1000


# ---------------------------------------------------------------------------
# Tests: FileWatcher.start / stop
# ---------------------------------------------------------------------------


class TestFileWatcherStartStop:
    @pytest.mark.asyncio
    async def test_start_without_watchfiles(self, tmp_path: Path):
        """If watchfiles is not installed, start() should warn and return."""
        cb = AsyncMock()
        fw = FileWatcher(tmp_path, cb)
        with patch("smolclaw.watcher.WATCHFILES_AVAILABLE", False):
            await fw.start()
        assert fw._task is None

    @pytest.mark.asyncio
    async def test_start_missing_agents_dir(self, tmp_path: Path):
        """If agents dir doesn't exist, watcher should not start."""
        cb = AsyncMock()
        missing = tmp_path / "nonexistent"
        fw = FileWatcher(missing, cb)
        with patch("smolclaw.watcher.WATCHFILES_AVAILABLE", True):
            await fw.start()
        assert fw._task is None

    @pytest.mark.asyncio
    async def test_start_creates_task(self, tmp_path: Path):
        """If watchfiles is available and dir exists, start() should create a background task."""
        cb = AsyncMock()
        fw = FileWatcher(tmp_path, cb)

        # Mock the watch loop to just set a flag and exit
        started = asyncio.Event()

        async def fake_watch_loop():
            started.set()
            await asyncio.Event().wait()

        with (
            patch("smolclaw.watcher.WATCHFILES_AVAILABLE", True),
            patch.object(fw, "_watch_loop", fake_watch_loop),
        ):
            await fw.start()
            assert fw._task is not None
            await asyncio.wait_for(started.wait(), timeout=1.0)
            await fw.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, tmp_path: Path):
        """stop() should cancel the running task."""
        cb = AsyncMock()
        fw = FileWatcher(tmp_path, cb)

        async def hang_forever():
            await asyncio.Event().wait()

        with (
            patch("smolclaw.watcher.WATCHFILES_AVAILABLE", True),
            patch.object(fw, "_watch_loop", hang_forever),
        ):
            await fw.start()
            assert fw._task is not None
            await fw.stop()
            assert fw._task is None

    @pytest.mark.asyncio
    async def test_stop_idempotent(self, tmp_path: Path):
        """stop() should be safe to call even if watcher was never started."""
        fw = FileWatcher(tmp_path, AsyncMock())
        await fw.stop()  # should not raise


# ---------------------------------------------------------------------------
# Tests: FileWatcher._handle_changes
# ---------------------------------------------------------------------------


class TestHandleChanges:
    @pytest.mark.asyncio
    async def test_reload_called_for_changed_agent(self, tmp_path: Path):
        """When a watched file changes, on_reload should be called."""
        agents_dir = tmp_path
        agent_dir = agents_dir / "tars"
        agent_dir.mkdir()
        (agent_dir / "agent.yaml").write_text("name: tars\nmodel: claude-sonnet-4-6\n")
        (agent_dir / "soul.md").write_text("You are TARS.")

        cb = AsyncMock()
        fw = FileWatcher(agents_dir, cb)

        mock_info = MagicMock()
        with patch("smolclaw.config.discover_agent", return_value=mock_info):
            # Simulate a Change enum value (1 = modified)
            changes = {(1, str(agent_dir / "soul.md"))}
            await fw._handle_changes(changes)

        cb.assert_awaited_once_with("tars", mock_info)

    @pytest.mark.asyncio
    async def test_ignores_non_watched_files(self, tmp_path: Path):
        """Changes to .py, .json, .env files should not trigger reload."""
        agents_dir = tmp_path
        agent_dir = agents_dir / "tars"
        agent_dir.mkdir()
        (agent_dir / "agent.yaml").write_text("name: tars\n")

        cb = AsyncMock()
        fw = FileWatcher(agents_dir, cb)

        changes = {(1, str(agent_dir / "script.py"))}
        await fw._handle_changes(changes)

        cb.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_agent_without_yaml(self, tmp_path: Path):
        """If agent.yaml is missing, skip reload for that agent."""
        agents_dir = tmp_path
        agent_dir = agents_dir / "ghost"
        agent_dir.mkdir()
        # No agent.yaml

        cb = AsyncMock()
        fw = FileWatcher(agents_dir, cb)

        changes = {(1, str(agent_dir / "soul.md"))}
        await fw._handle_changes(changes)

        cb.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_discover_error_handled(self, tmp_path: Path):
        """If discover_agent raises, it should be caught and logged."""
        agents_dir = tmp_path
        agent_dir = agents_dir / "broken"
        agent_dir.mkdir()
        (agent_dir / "agent.yaml").write_text("name: broken\n")

        cb = AsyncMock()
        fw = FileWatcher(agents_dir, cb)

        with patch("smolclaw.config.discover_agent", side_effect=ValueError("bad yaml")):
            changes = {(1, str(agent_dir / "agent.yaml"))}
            await fw._handle_changes(changes)  # should not raise

        cb.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_multiple_files_same_agent(self, tmp_path: Path):
        """Multiple changes in one agent should only trigger one reload."""
        agents_dir = tmp_path
        agent_dir = agents_dir / "tars"
        agent_dir.mkdir()
        (agent_dir / "agent.yaml").write_text("name: tars\n")

        cb = AsyncMock()
        fw = FileWatcher(agents_dir, cb)

        mock_info = MagicMock()
        with patch("smolclaw.config.discover_agent", return_value=mock_info):
            changes = {
                (1, str(agent_dir / "soul.md")),
                (1, str(agent_dir / "agents.md")),
                (1, str(agent_dir / "agent.yaml")),
            }
            await fw._handle_changes(changes)

        # Only one reload call per agent per batch
        cb.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_multiple_agents_in_one_batch(self, tmp_path: Path):
        """Changes in different agents should trigger separate reloads."""
        agents_dir = tmp_path
        for name in ("tars", "coach"):
            d = agents_dir / name
            d.mkdir()
            (d / "agent.yaml").write_text(f"name: {name}\n")

        cb = AsyncMock()
        fw = FileWatcher(agents_dir, cb)

        mock_info = MagicMock()
        with patch("smolclaw.config.discover_agent", return_value=mock_info):
            changes = {
                (1, str(agents_dir / "tars" / "soul.md")),
                (1, str(agents_dir / "coach" / "soul.md")),
            }
            await fw._handle_changes(changes)

        assert cb.await_count == 2

    @pytest.mark.asyncio
    async def test_changes_outside_agent_dir_ignored(self, tmp_path: Path):
        """Changes to files not under any agent dir should be ignored."""
        agents_dir = tmp_path
        cb = AsyncMock()
        fw = FileWatcher(agents_dir, cb)

        # File at root of agents_dir (not inside an agent subfolder)
        (agents_dir / "README.md").write_text("hello")
        changes = {(1, str(agents_dir / "README.md"))}
        await fw._handle_changes(changes)

        cb.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests: FileWatcher._watch_loop error handling
# ---------------------------------------------------------------------------


class TestWatchLoopErrors:
    @pytest.mark.asyncio
    async def test_watch_loop_handles_non_cancelled_exception(self, tmp_path: Path):
        """Non-CancelledError exceptions in _watch_loop should be caught and logged."""
        cb = AsyncMock()
        fw = FileWatcher(tmp_path, cb)

        # Make awatch raise a RuntimeError after yielding once
        async def fake_awatch(*args, **kwargs):
            raise RuntimeError("filesystem error")
            yield  # make it an async generator

        with patch("smolclaw.watcher.awatch", fake_awatch):
            await fw._watch_loop()  # should not raise

    @pytest.mark.asyncio
    async def test_watch_loop_propagates_cancelled_error(self, tmp_path: Path):
        """CancelledError in _watch_loop should propagate (not be swallowed)."""
        cb = AsyncMock()
        fw = FileWatcher(tmp_path, cb)

        async def fake_awatch(*args, **kwargs):
            raise asyncio.CancelledError()
            yield  # make it an async generator

        with (
            patch("smolclaw.watcher.awatch", fake_awatch),
            pytest.raises(asyncio.CancelledError),
        ):
            await fw._watch_loop()

    @pytest.mark.asyncio
    async def test_watch_loop_calls_handle_changes(self, tmp_path: Path):
        """_watch_loop should call _handle_changes for each batch from awatch."""
        cb = AsyncMock()
        fw = FileWatcher(tmp_path, cb)
        handled = []

        async def fake_handle(changes):
            handled.append(changes)

        async def fake_awatch(*args, **kwargs):
            yield {(1, str(tmp_path / "tars" / "soul.md"))}
            # After yielding once, stop by not yielding again

        with (
            patch("smolclaw.watcher.awatch", fake_awatch),
            patch.object(fw, "_handle_changes", fake_handle),
        ):
            await fw._watch_loop()

        assert len(handled) == 1
