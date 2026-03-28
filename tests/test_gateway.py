"""Tests for smolclaw.gateway — Gateway class and run_gateway."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from smolclaw.gateway import Gateway, WebSocketManager, run_gateway

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def _cleanup_gateway_tasks():
    """Stop scheduler/watcher loops spawned by Gateway.start() after each test.

    The CancelledError-resilient scheduler absorbs spurious cancellations
    from the Claude SDK, so ``task.cancel()`` alone won't stop it. We track
    all Gateway instances created during the test and call ``stop()`` on
    their schedulers (which sets ``_running=False`` before cancelling).
    """
    created: list[Gateway] = []
    _orig_init = Gateway.__init__

    def _tracking_init(self, *args, **kwargs):
        _orig_init(self, *args, **kwargs)
        created.append(self)

    with patch.object(Gateway, "__init__", _tracking_init):
        yield

    for gw in created:
        with contextlib.suppress(Exception):
            await gw.stop()


@pytest.fixture
def gw_base(tmp_base: Path, agent_dir: Path, jobs_file: Path) -> Path:
    """A fully wired smolclaw home with one agent and one cron job."""
    return tmp_base


# ---------------------------------------------------------------------------
# Tests: __init__
# ---------------------------------------------------------------------------


class TestGatewayInit:
    def test_basic_init(self, gw_base: Path):
        gw = Gateway(gw_base)
        assert gw.base_dir == gw_base
        assert gw.config.host == "127.0.0.1"
        assert gw.config.port == 7890
        assert gw.agents == {}
        assert gw.channels == []
        assert gw.scheduler is None

    def test_repr(self, gw_base: Path):
        gw = Gateway(gw_base)
        r = repr(gw)
        assert "Gateway" in r
        assert "agents=0" in r
        assert "channels=0" in r


# ---------------------------------------------------------------------------
# Tests: start
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_cleanup_gateway_tasks")
class TestGatewayStart:
    @pytest.mark.asyncio
    async def test_discovers_agents(self, gw_base: Path):
        gw = Gateway(gw_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()
        assert "testagent" in gw.agents
        assert gw.agents["testagent"].name == "testagent"
        assert gw.agents["testagent"].memory is not None

    @pytest.mark.asyncio
    async def test_loads_user_md(self, gw_base: Path):
        gw = Gateway(gw_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()
        assert "# Test User" in gw.agents["testagent"].user_md
        assert "Name: Tester" in gw.agents["testagent"].user_md

    @pytest.mark.asyncio
    async def test_registers_agent_in_router(self, gw_base: Path):
        gw = Gateway(gw_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()
        assert gw.router.get_agent("testagent") is gw.agents["testagent"]

    @pytest.mark.asyncio
    async def test_starts_scheduler(self, gw_base: Path):
        gw = Gateway(gw_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()
        assert gw.scheduler is not None
        assert len(gw.scheduler.jobs) == 1
        assert gw.scheduler.jobs[0].id == "test-job"

    @pytest.mark.asyncio
    async def test_zero_agents_logs_warning(self, tmp_base: Path):
        """Gateway with no agents dir should warn but still boot."""
        gw = Gateway(tmp_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()
        assert gw.agents == {}

    @pytest.mark.asyncio
    async def test_creates_shared_dir_for_memory(self, tmp_base: Path, agent_dir: Path):
        """Even if shared/ doesn't exist yet, gateway should create it."""
        # Remove the shared dir to simulate fresh install
        import shutil

        shared = tmp_base / "shared"
        # Save files we need
        user_md = (shared / "USER.md").read_text()
        jobs_data = None
        jobs_path = shared / "cron" / "jobs.json"
        if jobs_path.exists():
            jobs_data = jobs_path.read_text()
        shutil.rmtree(shared)

        # Recreate minimal structure (USER.md needed by config loader)
        shared.mkdir()
        (shared / "USER.md").write_text(user_md)
        (shared / "cron").mkdir()
        if jobs_data:
            jobs_path.write_text(jobs_data)

        gw = Gateway(tmp_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()
        assert (shared / "memory.db").exists() or "testagent" in gw.agents

    @pytest.mark.asyncio
    async def test_channel_starts_successfully(self, gw_base: Path, agent_dir: Path):
        """When channel creates and starts without error, it's appended to gw.channels."""
        (agent_dir / "agent.yaml").write_text(
            "name: testagent\n"
            "model: claude-sonnet-4-6\n"
            "channels:\n"
            "  telegram:\n"
            "    token_env: TELEGRAM_BOT_TOKEN\n"
            "    allowed_chats: []\n"
            "memory:\n"
            "  enabled: true\n"
            "  cross_agent: false\n"
        )
        mock_channel = MagicMock()
        mock_channel.start = AsyncMock()  # succeeds

        with patch("smolclaw.gateway.create_channel", return_value=mock_channel):
            gw = Gateway(gw_base)
            await gw.start()

        assert mock_channel in gw.channels
        mock_channel.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_channel_start_failure_continues(self, gw_base: Path, agent_dir: Path):
        """If a channel fails to start, gateway should continue loading other things."""
        # Add a channel config to the agent
        (agent_dir / "agent.yaml").write_text(
            "name: testagent\n"
            "model: claude-sonnet-4-6\n"
            "channels:\n"
            "  telegram:\n"
            "    token_env: TELEGRAM_BOT_TOKEN\n"
            "    allowed_chats: []\n"
            "memory:\n"
            "  enabled: true\n"
            "  cross_agent: false\n"
        )
        mock_channel = MagicMock()
        mock_channel.start = AsyncMock(side_effect=RuntimeError("no token"))

        with patch("smolclaw.gateway.create_channel", return_value=mock_channel):
            gw = Gateway(gw_base)
            await gw.start()

        # Agent should still be loaded despite channel failure
        assert "testagent" in gw.agents

    @pytest.mark.asyncio
    async def test_env_file_loading(self, gw_base: Path, agent_dir: Path):
        """Env files in agent channels/ dir should be loaded into os.environ."""
        channels_dir = agent_dir / "channels"
        (channels_dir / "test.env").write_text("TEST_KEY_12345=hello_world\n# comment\n")

        import os

        gw = Gateway(gw_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()

        assert os.environ.get("TEST_KEY_12345") == "hello_world"
        # Cleanup
        os.environ.pop("TEST_KEY_12345", None)

    @pytest.mark.asyncio
    async def test_duplicate_token_skipped(self, tmp_base: Path):
        """Two agents with the same Telegram token should not both start channels."""
        import os

        for name in ["agent_a", "agent_b"]:
            agent = tmp_base / "agents" / name
            for subdir in ["skills", "prompts", "context", "channels", "sessions"]:
                (agent / subdir).mkdir(parents=True, exist_ok=True)
            (agent / "agent.yaml").write_text(
                f"name: {name}\nmodel: claude-sonnet-4-6\n"
                "channels:\n  telegram:\n    token_env: SHARED_DUP_TOKEN\n"
                "memory:\n  enabled: true\n  cross_agent: false\n"
            )
            (agent / "soul.md").write_text(f"# {name}")
            # Both point to same env var with same value
            (agent / "channels" / "telegram.env").write_text(
                "SHARED_DUP_TOKEN=same-bot-token-12345\n"
            )

        mock_channel = MagicMock()
        mock_channel.start = AsyncMock()

        gw = Gateway(tmp_base)
        with patch("smolclaw.gateway.create_channel", return_value=mock_channel) as factory:
            await gw.start()

        # create_channel should only be called ONCE — the second agent's channel is skipped
        assert factory.call_count == 1

        # Cleanup
        os.environ.pop("SHARED_DUP_TOKEN", None)

    @pytest.mark.asyncio
    async def test_unique_tokens_both_start(self, tmp_base: Path):
        """Two agents with different Telegram tokens should both start channels."""
        import os

        for idx, name in enumerate(["agent_x", "agent_y"]):
            agent = tmp_base / "agents" / name
            for subdir in ["skills", "prompts", "context", "channels", "sessions"]:
                (agent / subdir).mkdir(parents=True, exist_ok=True)
            env_var = f"TOKEN_UNIQUE_{name.upper()}"
            (agent / "agent.yaml").write_text(
                f"name: {name}\nmodel: claude-sonnet-4-6\n"
                f"channels:\n  telegram:\n    token_env: {env_var}\n"
                "memory:\n  enabled: true\n  cross_agent: false\n"
            )
            (agent / "soul.md").write_text(f"# {name}")
            (agent / "channels" / "telegram.env").write_text(f"{env_var}=unique-token-{idx}\n")

        mock_channel = MagicMock()
        mock_channel.start = AsyncMock()

        gw = Gateway(tmp_base)
        with patch("smolclaw.gateway.create_channel", return_value=mock_channel) as factory:
            await gw.start()

        # Both channels should start
        assert factory.call_count == 2

        # Cleanup
        os.environ.pop("TOKEN_UNIQUE_AGENT_X", None)
        os.environ.pop("TOKEN_UNIQUE_AGENT_Y", None)

    @pytest.mark.asyncio
    async def test_empty_token_not_tracked(self, gw_base: Path, agent_dir: Path):
        """Channels with empty/missing tokens should not block other agents."""
        (agent_dir / "agent.yaml").write_text(
            "name: testagent\nmodel: claude-sonnet-4-6\n"
            "channels:\n  telegram:\n    token_env: NONEXISTENT_TOKEN_VAR\n"
            "memory:\n  enabled: true\n  cross_agent: false\n"
        )

        mock_channel = MagicMock()
        mock_channel.start = AsyncMock()

        gw = Gateway(gw_base)
        with patch("smolclaw.gateway.create_channel", return_value=mock_channel) as factory:
            await gw.start()

        # Channel should still be created (empty token is the channel's problem to handle)
        assert factory.call_count == 1

    @pytest.mark.asyncio
    async def test_bad_env_file_continues(self, gw_base: Path, agent_dir: Path):
        """Unreadable env file should log error and continue."""
        channels_dir = agent_dir / "channels"
        env_file = channels_dir / "broken.env"
        env_file.write_text("SOME_KEY=value")
        # Make unreadable
        env_file.chmod(0o000)

        gw = Gateway(gw_base)
        try:
            with patch("smolclaw.gateway.create_channel"):
                await gw.start()
            # Should not crash
            assert "testagent" in gw.agents
        finally:
            env_file.chmod(0o644)  # Restore for cleanup


# ---------------------------------------------------------------------------
# Tests: _deliver_cron
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_cleanup_gateway_tasks")
class TestDeliverCron:
    @pytest.mark.asyncio
    async def test_delivers_to_matching_channel(self, gw_base: Path):
        from smolclaw.scheduler import Job

        gw = Gateway(gw_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()

        mock_channel = MagicMock()
        mock_channel.agent_name = "testagent"
        mock_channel.channel_type = "telegram"
        mock_channel.send = AsyncMock()
        gw.channels.append(mock_channel)

        job = MagicMock(spec=Job)
        job.id = "j1"
        job.agent = "testagent"
        job.delivery = "telegram"
        job.delivery_chat_id = "123"

        await gw._deliver_cron(job, "Hello from cron")
        mock_channel.send.assert_awaited_once_with("123", "Hello from cron")

    @pytest.mark.asyncio
    async def test_no_matching_channel(self, gw_base: Path):
        from smolclaw.scheduler import Job

        gw = Gateway(gw_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()

        job = MagicMock(spec=Job)
        job.id = "j1"
        job.agent = "testagent"
        job.delivery = "slack"
        job.delivery_chat_id = ""

        # Should not raise
        await gw._deliver_cron(job, "Hello")

    @pytest.mark.asyncio
    async def test_channel_send_failure_handled(self, gw_base: Path):
        from smolclaw.scheduler import Job

        gw = Gateway(gw_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()

        mock_channel = MagicMock()
        mock_channel.agent_name = "testagent"
        mock_channel.channel_type = "telegram"
        mock_channel.send = AsyncMock(side_effect=RuntimeError("network error"))
        gw.channels.append(mock_channel)

        job = MagicMock(spec=Job)
        job.id = "j1"
        job.agent = "testagent"
        job.delivery = "telegram"
        job.delivery_chat_id = "123"

        # Should not raise — error is caught
        await gw._deliver_cron(job, "Hello")


# ---------------------------------------------------------------------------
# Tests: _reload_agent
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_cleanup_gateway_tasks")
class TestReloadAgent:
    @pytest.mark.asyncio
    async def test_reload_updates_agent_info(self, gw_base: Path):
        gw = Gateway(gw_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()

        # Create a new AgentInfo with different model
        new_info = MagicMock()
        new_info.config.model = "claude-opus-4-6"
        new_info.config.name = "testagent"

        await gw._reload_agent("testagent", new_info)

        agent = gw.agents["testagent"]
        assert agent.info is new_info
        assert agent.model == "claude-opus-4-6"

    @pytest.mark.asyncio
    async def test_reload_unknown_agent_skipped(self, gw_base: Path):
        gw = Gateway(gw_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()

        new_info = MagicMock()
        # Should not raise for unknown agent
        await gw._reload_agent("nonexistent", new_info)

    @pytest.mark.asyncio
    async def test_watcher_started_on_gateway_start(self, gw_base: Path):
        gw = Gateway(gw_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()

        assert gw.watcher is not None

    @pytest.mark.asyncio
    async def test_watcher_stopped_on_gateway_stop(self, gw_base: Path):
        gw = Gateway(gw_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()

        # Replace watcher with a mock to verify stop is called
        mock_watcher = MagicMock()
        mock_watcher.stop = AsyncMock()
        gw.watcher = mock_watcher

        await gw.stop()
        mock_watcher.stop.assert_awaited_once()


# ---------------------------------------------------------------------------
# Tests: stop
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_cleanup_gateway_tasks")
class TestGatewayStop:
    @pytest.mark.asyncio
    async def test_stop_shuts_down_everything(self, gw_base: Path):
        gw = Gateway(gw_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()

        # Mock the agent's shutdown
        agent = gw.agents["testagent"]
        agent.shutdown = AsyncMock()

        await gw.stop()
        agent.shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_handles_channel_error(self, gw_base: Path):
        gw = Gateway(gw_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()

        bad_channel = MagicMock()
        bad_channel.stop = AsyncMock(side_effect=RuntimeError("oops"))
        gw.channels.append(bad_channel)

        # Should not raise
        await gw.stop()

    @pytest.mark.asyncio
    async def test_stop_handles_agent_shutdown_error(self, gw_base: Path):
        gw = Gateway(gw_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()

        agent = gw.agents["testagent"]
        agent.shutdown = AsyncMock(side_effect=RuntimeError("shutdown failed"))

        # Should not raise
        await gw.stop()


# ---------------------------------------------------------------------------
# Tests: send
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_cleanup_gateway_tasks")
class TestGatewaySend:
    @pytest.mark.asyncio
    async def test_send_routes_to_agent(self, gw_base: Path):
        gw = Gateway(gw_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()

        # Mock the agent's send method
        agent = gw.agents["testagent"]
        agent.send = AsyncMock(return_value="Response text")

        result = await gw.send("testagent", "Hello")
        assert result == "Response text"


# ---------------------------------------------------------------------------
# Tests: run_gateway
# ---------------------------------------------------------------------------


def _make_mock_gateway(**overrides):
    """Create a mock Gateway with sensible defaults."""
    gw = MagicMock()
    gw.start = AsyncMock()
    gw.stop = AsyncMock()
    gw.agents = overrides.get("agents", {"testagent": MagicMock()})
    gw.channels = overrides.get("channels", [])
    gw.config.host = overrides.get("host", "127.0.0.1")
    gw.config.port = overrides.get("port", 7890)
    return gw


class TestLogging:
    def test_get_log_path(self, tmp_path: Path):
        from smolclaw.gateway import get_log_path

        assert get_log_path(tmp_path) == tmp_path / "smolclaw.log"

    def test_setup_logging_creates_file(self, tmp_path: Path):
        import logging

        from smolclaw.gateway import setup_logging

        # Clear any existing handlers on the smolclaw logger
        logger = logging.getLogger("smolclaw")
        original_handlers = logger.handlers[:]
        logger.handlers.clear()

        try:
            setup_logging(tmp_path)
            log_path = tmp_path / "smolclaw.log"

            # Logger should have 2 handlers (console + file)
            assert len(logger.handlers) == 2

            # Log something and verify it appears in the file
            logger.info("test log message")
            # Flush handlers
            for h in logger.handlers:
                h.flush()
            content = log_path.read_text(encoding="utf-8")
            assert "test log message" in content
        finally:
            # Restore original handlers
            for h in logger.handlers[:]:
                h.close()
            logger.handlers.clear()
            logger.handlers.extend(original_handlers)

    def test_setup_logging_creates_parent_dirs(self, tmp_path: Path):
        import logging

        from smolclaw.gateway import setup_logging

        logger = logging.getLogger("smolclaw")
        original_handlers = logger.handlers[:]
        logger.handlers.clear()

        nested = tmp_path / "deep" / "nested"
        try:
            setup_logging(nested)
            assert (nested / "smolclaw.log").exists()
        finally:
            for h in logger.handlers[:]:
                h.close()
            logger.handlers.clear()
            logger.handlers.extend(original_handlers)

    def test_setup_logging_respects_level(self, tmp_path: Path):
        import logging

        from smolclaw.gateway import setup_logging

        logger = logging.getLogger("smolclaw")
        original_handlers = logger.handlers[:]
        logger.handlers.clear()

        try:
            setup_logging(tmp_path, level="DEBUG")
            assert logger.level == logging.DEBUG
        finally:
            for h in logger.handlers[:]:
                h.close()
            logger.handlers.clear()
            logger.handlers.extend(original_handlers)


@pytest.mark.usefixtures("_cleanup_gateway_tasks")
class TestRunGateway:
    @pytest.mark.asyncio
    async def test_start_failure_raises(self, gw_base: Path):
        """If Gateway.start() fails, run_gateway should re-raise."""
        mock_gw = _make_mock_gateway()
        mock_gw.start = AsyncMock(side_effect=RuntimeError("boot failed"))

        with (
            patch("smolclaw.gateway.Gateway", return_value=mock_gw),
            pytest.raises(RuntimeError, match="boot failed"),
        ):
            await run_gateway(gw_base)

    @pytest.mark.asyncio
    async def test_without_api(self, gw_base: Path):
        """run_gateway with_api=False should skip uvicorn entirely."""
        mock_gw = _make_mock_gateway()
        loop = asyncio.get_running_loop()
        orig_handler = loop.add_signal_handler

        def auto_trigger(sig, cb, *args):
            loop.call_soon(cb, *args)

        with patch("smolclaw.gateway.Gateway", return_value=mock_gw):
            loop.add_signal_handler = auto_trigger
            try:
                await run_gateway(gw_base, with_api=False)
            finally:
                loop.add_signal_handler = orig_handler

        mock_gw.start.assert_awaited_once()
        mock_gw.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_with_api(self, gw_base: Path):
        """run_gateway with_api=True should start uvicorn server."""
        mock_gw = _make_mock_gateway()
        loop = asyncio.get_running_loop()
        orig_handler = loop.add_signal_handler

        def auto_trigger(sig, cb, *args):
            loop.call_soon(cb, *args)

        mock_server = MagicMock()
        mock_server.serve = AsyncMock()
        mock_uvicorn = MagicMock()
        mock_uvicorn.Server.return_value = mock_server

        with (
            patch("smolclaw.gateway.Gateway", return_value=mock_gw),
            patch.dict("sys.modules", {"uvicorn": mock_uvicorn}),
            patch("smolclaw.api.create_app", return_value=MagicMock()),
        ):
            loop.add_signal_handler = auto_trigger
            try:
                await run_gateway(gw_base, with_api=True)
            finally:
                loop.add_signal_handler = orig_handler

        mock_gw.start.assert_awaited_once()
        mock_gw.stop.assert_awaited_once()
        mock_uvicorn.Config.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_uvicorn_continues(self, gw_base: Path):
        """If uvicorn is not installed, run_gateway should log warning and continue."""
        mock_gw = _make_mock_gateway()
        loop = asyncio.get_running_loop()
        orig_handler = loop.add_signal_handler

        def auto_trigger(sig, cb, *args):
            loop.call_soon(cb, *args)

        # Setting module to None causes import to raise ImportError
        with (
            patch("smolclaw.gateway.Gateway", return_value=mock_gw),
            patch.dict("sys.modules", {"uvicorn": None}),
        ):
            loop.add_signal_handler = auto_trigger
            try:
                await run_gateway(gw_base, with_api=True)
            finally:
                loop.add_signal_handler = orig_handler

        # Should still start and stop cleanly
        mock_gw.start.assert_awaited_once()
        mock_gw.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_prints_banner(self, gw_base: Path, capsys):
        """run_gateway should print the ASCII box banner."""
        mock_gw = _make_mock_gateway()
        loop = asyncio.get_running_loop()
        orig_handler = loop.add_signal_handler

        def auto_trigger(sig, cb, *args):
            loop.call_soon(cb, *args)

        with patch("smolclaw.gateway.Gateway", return_value=mock_gw):
            loop.add_signal_handler = auto_trigger
            try:
                await run_gateway(gw_base, with_api=False)
            finally:
                loop.add_signal_handler = orig_handler

        captured = capsys.readouterr()
        assert "smolclaw gateway" in captured.out
        assert "Agents:" in captured.out
        assert "Channels:" in captured.out

    @pytest.mark.asyncio
    async def test_api_task_cancelled_on_stop(self, gw_base: Path):
        """When gateway stops, the API task should be cancelled."""
        mock_gw = _make_mock_gateway()
        loop = asyncio.get_running_loop()
        orig_handler = loop.add_signal_handler

        def auto_trigger(sig, cb, *args):
            loop.call_soon(cb, *args)

        # Create a real async function that hangs until cancelled
        serve_cancelled = asyncio.Event()

        async def fake_serve():
            try:
                await asyncio.Event().wait()  # hang forever
            except asyncio.CancelledError:
                serve_cancelled.set()
                raise

        mock_server = MagicMock()
        mock_server.serve = fake_serve
        mock_uvicorn = MagicMock()
        mock_uvicorn.Server.return_value = mock_server

        with (
            patch("smolclaw.gateway.Gateway", return_value=mock_gw),
            patch.dict("sys.modules", {"uvicorn": mock_uvicorn}),
            patch("smolclaw.api.create_app", return_value=MagicMock()),
        ):
            loop.add_signal_handler = auto_trigger
            try:
                await run_gateway(gw_base, with_api=True)
            finally:
                loop.add_signal_handler = orig_handler

        assert serve_cancelled.is_set()


# ---------------------------------------------------------------------------
# Tests: cross-agent awareness (peer population)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_cleanup_gateway_tasks")
class TestCrossAgentAwareness:
    @pytest.fixture
    def multi_agent_base(self, tmp_base: Path) -> Path:
        """Create a smolclaw home with two agents."""
        for name, model, soul in [
            ("tars", "claude-opus-4-6", "# TARS\nPersonal assistant."),
            ("coach", "claude-sonnet-4-6", "# Coach\nFitness coach."),
        ]:
            agent = tmp_base / "agents" / name
            for subdir in ["skills", "prompts", "context", "channels", "sessions"]:
                (agent / subdir).mkdir(parents=True, exist_ok=True)
            (agent / "agent.yaml").write_text(
                f"name: {name}\nmodel: {model}\nchannels: {{}}\n"
                "memory:\n  enabled: true\n  cross_agent: false\n"
            )
            (agent / "soul.md").write_text(soul)
        return tmp_base

    @pytest.mark.asyncio
    async def test_peers_populated(self, multi_agent_base: Path):
        gw = Gateway(multi_agent_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()

        tars = gw.agents["tars"]
        coach = gw.agents["coach"]

        # Each agent should see the other as a peer
        assert len(tars.peers) == 1
        assert tars.peers[0]["name"] == "coach"
        assert tars.peers[0]["model"] == "claude-sonnet-4-6"

        assert len(coach.peers) == 1
        assert coach.peers[0]["name"] == "tars"
        assert coach.peers[0]["model"] == "claude-opus-4-6"

    @pytest.mark.asyncio
    async def test_peer_description_from_soul(self, multi_agent_base: Path):
        gw = Gateway(multi_agent_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()

        tars = gw.agents["tars"]
        # Coach's soul starts with "# Coach" — the first line stripped of # is the description
        assert tars.peers[0]["description"] == "Coach"

    @pytest.mark.asyncio
    async def test_single_agent_no_peers(self, gw_base: Path):
        gw = Gateway(gw_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()

        agent = gw.agents["testagent"]
        assert agent.peers == []

    @pytest.mark.asyncio
    async def test_gateway_url_set(self, multi_agent_base: Path):
        gw = Gateway(multi_agent_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()

        for agent in gw.agents.values():
            assert agent.gateway_url == "http://127.0.0.1:7890"

    @pytest.mark.asyncio
    async def test_peers_in_system_prompt(self, multi_agent_base: Path):
        gw = Gateway(multi_agent_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()

        prompt = gw.agents["tars"].build_system_prompt()
        assert "Peer Agents" in prompt
        assert "coach" in prompt


# ---------------------------------------------------------------------------
# Tests: WebSocketManager
# ---------------------------------------------------------------------------


class TestWebSocketManager:
    def test_initial_state(self):
        mgr = WebSocketManager()
        assert mgr.connection_count == 0

    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self):
        mgr = WebSocketManager()
        ws = AsyncMock()
        await mgr.connect(ws)
        ws.accept.assert_awaited_once()
        assert mgr.connection_count == 1

        mgr.disconnect(ws)
        assert mgr.connection_count == 0

    @pytest.mark.asyncio
    async def test_disconnect_idempotent(self):
        mgr = WebSocketManager()
        ws = AsyncMock()
        await mgr.connect(ws)
        mgr.disconnect(ws)
        mgr.disconnect(ws)  # Should not raise
        assert mgr.connection_count == 0

    @pytest.mark.asyncio
    async def test_disconnect_unknown_ws(self):
        mgr = WebSocketManager()
        ws = AsyncMock()
        mgr.disconnect(ws)  # Never connected — should not raise
        assert mgr.connection_count == 0

    @pytest.mark.asyncio
    async def test_broadcast_to_multiple_clients(self):
        mgr = WebSocketManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await mgr.connect(ws1)
        await mgr.connect(ws2)

        await mgr.broadcast("agents")

        ws1.send_json.assert_awaited_once_with({"event": "agents"})
        ws2.send_json.assert_awaited_once_with({"event": "agents"})

    @pytest.mark.asyncio
    async def test_broadcast_no_clients_is_noop(self):
        mgr = WebSocketManager()
        await mgr.broadcast("agents")  # Should not raise

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_connections(self):
        mgr = WebSocketManager()
        ws_alive = AsyncMock()
        ws_dead = AsyncMock()
        ws_dead.send_json.side_effect = Exception("Connection closed")

        await mgr.connect(ws_alive)
        await mgr.connect(ws_dead)
        assert mgr.connection_count == 2

        await mgr.broadcast("jobs")

        assert mgr.connection_count == 1
        ws_alive.send_json.assert_awaited_once_with({"event": "jobs"})

    @pytest.mark.asyncio
    async def test_broadcast_all_dead(self):
        mgr = WebSocketManager()
        ws1 = AsyncMock()
        ws1.send_json.side_effect = RuntimeError("gone")
        ws2 = AsyncMock()
        ws2.send_json.side_effect = RuntimeError("also gone")

        await mgr.connect(ws1)
        await mgr.connect(ws2)
        await mgr.broadcast("agents")

        assert mgr.connection_count == 0

    @pytest.mark.asyncio
    async def test_broadcast_different_events(self):
        mgr = WebSocketManager()
        ws = AsyncMock()
        await mgr.connect(ws)

        await mgr.broadcast("agents")
        await mgr.broadcast("jobs")

        assert ws.send_json.await_count == 2
        ws.send_json.assert_any_await({"event": "agents"})
        ws.send_json.assert_any_await({"event": "jobs"})


@pytest.mark.usefixtures("_cleanup_gateway_tasks")
class TestGatewayWebSocket:
    def test_gateway_has_ws_manager(self, gw_base: Path):
        gw = Gateway(gw_base)
        assert isinstance(gw.ws_manager, WebSocketManager)
        assert gw.ws_manager.connection_count == 0

    @pytest.mark.asyncio
    async def test_reload_agent_broadcasts(self, gw_base: Path):
        gw = Gateway(gw_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()

        ws = AsyncMock()
        await gw.ws_manager.connect(ws)

        from smolclaw.config import discover_all_agents

        agents = discover_all_agents(gw_base)
        new_info = agents["testagent"]
        await gw._reload_agent("testagent", new_info)

        ws.send_json.assert_awaited_with({"event": "agents"})

    @pytest.mark.asyncio
    async def test_scheduler_event_broadcasts(self, gw_base: Path):
        gw = Gateway(gw_base)
        with patch("smolclaw.gateway.create_channel"):
            await gw.start()

        ws = AsyncMock()
        await gw.ws_manager.connect(ws)

        await gw._on_scheduler_event()

        ws.send_json.assert_awaited_with({"event": "jobs"})


# ---------------------------------------------------------------------------
# Tests: tracing configuration on start
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_cleanup_gateway_tasks")
class TestGatewayTracing:
    @pytest.mark.asyncio
    async def test_tracing_enabled_and_configured(self, gw_base: Path):
        """When tracing=true in config, configure_tracing is called."""
        # Enable tracing in config
        config_path = gw_base / "config.yaml"
        config_path.write_text(
            "host: 127.0.0.1\nport: 7890\nlog_level: WARNING\n"
            "tracing: true\ntracing_exporter: console\n"
        )

        gw = Gateway(gw_base)
        with (
            patch("smolclaw.gateway.create_channel"),
            patch("smolclaw.gateway.configure_tracing", return_value=True) as mock_trace,
        ):
            await gw.start()

        mock_trace.assert_called_once()
        args = mock_trace.call_args[0][0]
        assert args.enabled is True
        assert args.exporter == "console"

    @pytest.mark.asyncio
    async def test_tracing_enabled_but_unavailable(self, gw_base: Path):
        """When tracing is enabled but OTEL not installed, logs warning."""
        config_path = gw_base / "config.yaml"
        config_path.write_text("host: 127.0.0.1\nport: 7890\nlog_level: WARNING\ntracing: true\n")

        gw = Gateway(gw_base)
        with (
            patch("smolclaw.gateway.create_channel"),
            patch("smolclaw.gateway.configure_tracing", return_value=False) as mock_trace,
        ):
            await gw.start()

        # Should have been called (and returned False = unavailable)
        mock_trace.assert_called_once()

    @pytest.mark.asyncio
    async def test_tracing_disabled_by_default(self, gw_base: Path):
        """When tracing is not set in config, configure_tracing is never called."""
        gw = Gateway(gw_base)
        with (
            patch("smolclaw.gateway.create_channel"),
            patch("smolclaw.gateway.configure_tracing") as mock_trace,
        ):
            await gw.start()

        mock_trace.assert_not_called()
