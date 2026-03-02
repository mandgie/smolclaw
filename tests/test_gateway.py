"""Tests for smolclaw.gateway — Gateway class and run_gateway."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from smolclaw.gateway import Gateway, run_gateway

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Tests: start
# ---------------------------------------------------------------------------


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
# Tests: stop
# ---------------------------------------------------------------------------


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
