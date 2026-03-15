"""Gateway — single process that boots all agents, channels, scheduler, and API."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path

__all__ = ["Gateway", "get_log_path", "run_gateway", "setup_logging"]

import contextlib

from . import __version__
from .agent import Agent
from .channel import Channel, create_channel
from .config import (
    AgentInfo,
    GatewayConfig,
    discover_all_agents,
    load_gateway_config,
    load_shared_user_md,
)
from .memory import Memory
from .router import Router
from .scheduler import Job, Scheduler
from .tracing import TracingConfig, configure_tracing
from .watcher import FileWatcher

log = logging.getLogger("smolclaw")


class Gateway:
    """The smolclaw gateway — single process running everything."""

    def __init__(self, base_dir: Path):
        """Initialize the gateway from a smolclaw home directory.

        Args:
            base_dir: Path to the smolclaw home (e.g. ~/.smolclaw).
        """
        self.base_dir = base_dir
        self.config: GatewayConfig = load_gateway_config(base_dir)
        self.router = Router()
        self.agents: dict[str, Agent] = {}
        self.channels: list[Channel] = []
        self.scheduler: Scheduler | None = None
        self.watcher: FileWatcher | None = None
        self._user_md = ""

    def __repr__(self) -> str:
        return (
            f"Gateway(base={self.base_dir}, agents={len(self.agents)},"
            f" channels={len(self.channels)})"
        )

    async def start(self) -> None:
        """Boot everything: agents, channels, scheduler."""
        log.info(f"smolclaw gateway starting (base={self.base_dir})")

        # Configure tracing if enabled
        if self.config.tracing:
            tracing_cfg = TracingConfig(
                enabled=True,
                exporter=self.config.tracing_exporter,
                endpoint=self.config.tracing_endpoint,
            )
            if configure_tracing(tracing_cfg):
                log.info("OpenTelemetry tracing: enabled")
            else:
                log.warning(
                    "OpenTelemetry tracing: requested but unavailable (pip install smolclaw[otel])"
                )

        # Load shared context
        self._user_md = load_shared_user_md(self.base_dir)

        # Discover and load agents
        agents_dir = self.base_dir / self.config.agents_dir
        agent_infos = discover_all_agents(self.base_dir)

        if not agent_infos:
            log.warning("No agents discovered — gateway will run with zero agents")

        # Ensure shared dir exists for memory DB
        shared_dir = self.base_dir / self.config.shared_dir
        shared_dir.mkdir(parents=True, exist_ok=True)
        memory_db = shared_dir / "memory.db"

        for name, info in agent_infos.items():
            agent = Agent(info, user_md=self._user_md)

            # Attach namespaced memory
            agent.memory = Memory(memory_db, agent=name)

            self.agents[name] = agent
            self.router.register_agent(agent)
            log.info(f"Loaded agent: {name} (model={info.config.model})")

        # Set gateway URL for cross-agent API calls
        gateway_url = f"http://{self.config.host}:{self.config.port}"

        # Populate peer agent info for cross-agent awareness
        for name, agent in self.agents.items():
            agent.gateway_url = gateway_url
            agent.peers = [
                {
                    "name": peer_name,
                    "model": peer.model,
                    "description": peer.info.soul.split("\n")[0].strip("# ").strip()
                    if peer.info.soul
                    else "",
                }
                for peer_name, peer in self.agents.items()
                if peer_name != name
            ]

        # Load channel env files and start channels
        # Track active tokens per channel type to prevent duplicate polling
        # (e.g. two Telegram agents with the same bot token cause 409 Conflict errors)
        active_tokens: dict[str, str] = {}  # token_value -> agent_name

        for name, agent in self.agents.items():
            # Load env files from agent's channels/ directory
            channels_dir = agent.info.path / "channels"
            if channels_dir.exists():
                for env_file in channels_dir.glob("*.env"):
                    try:
                        for line in env_file.read_text().splitlines():
                            line = line.strip()
                            if line and not line.startswith("#") and "=" in line:
                                key, _, value = line.partition("=")
                                os.environ.setdefault(key.strip(), value.strip())
                    except OSError as e:
                        log.error(f"Failed to read env file {env_file}: {e}")

            for ch_type, ch_config in agent.info.config.channels.items():
                # Check for duplicate tokens (same bot used by multiple agents)
                token_value = os.environ.get(ch_config.token_env, "")
                if token_value:
                    token_key = f"{ch_type}:{token_value}"
                    if token_key in active_tokens:
                        owner = active_tokens[token_key]
                        log.warning(
                            f"[{name}] Skipping {ch_type} channel — token "
                            f"{ch_config.token_env} already in use by agent '{owner}'. "
                            f"Each agent needs a unique bot token to avoid polling conflicts."
                        )
                        continue
                    active_tokens[token_key] = name

                try:
                    channel = create_channel(ch_type, name, ch_config, self.router)
                    await channel.start()
                    self.channels.append(channel)
                    log.info(f"Started {ch_type} channel for {name}")
                except Exception as e:
                    log.error(f"Failed to start {ch_type} for {name}: {e}")

        # Start scheduler
        jobs_path = self.base_dir / self.config.shared_dir / "cron" / "jobs.json"
        self.scheduler = Scheduler(
            jobs_path, agents_dir, self.router, deliver_callback=self._deliver_cron
        )

        await self.scheduler.start()

        # Start file watcher for hot-reload
        self.watcher = FileWatcher(agents_dir, self._reload_agent)
        await self.watcher.start()

        agent_count = len(self.agents)
        channel_count = len(self.channels)
        job_count = len(self.scheduler.jobs) if self.scheduler else 0

        log.info(
            f"smolclaw gateway ready: "
            f"{agent_count} agents, {channel_count} channels, {job_count} jobs"
        )

    async def _reload_agent(self, agent_name: str, new_info: AgentInfo) -> None:
        """Hot-reload an agent with updated filesystem info."""
        if agent_name not in self.agents:
            log.warning(f"[reload] Agent {agent_name} not in registry, skipping")
            return

        agent = self.agents[agent_name]
        agent.info = new_info
        agent.model = new_info.config.model
        log.info(f"[reload] Agent {agent_name} updated (model={new_info.config.model})")

    async def _deliver_cron(self, job: Job, text: str) -> None:
        """Deliver cron job output to the right channel."""
        for channel in self.channels:
            if channel.agent_name == job.agent and channel.channel_type == job.delivery:
                try:
                    await channel.send(job.delivery_chat_id, text)
                except Exception as e:
                    log.error(f"Failed to deliver cron job {job.id} via {job.delivery}: {e}")
                return
        log.warning(f"No {job.delivery} channel found for agent {job.agent}")

    async def stop(self) -> None:
        """Graceful shutdown."""
        log.info("smolclaw gateway shutting down")

        if self.watcher:
            await self.watcher.stop()

        if self.scheduler:
            await self.scheduler.stop()

        for channel in self.channels:
            try:
                await channel.stop()
            except Exception as e:
                log.error(f"Error stopping channel: {e}")

        for agent in self.agents.values():
            try:
                await agent.shutdown()
            except Exception as e:
                log.error(f"Error shutting down agent {agent.name}: {e}")

        log.info("smolclaw gateway stopped")

    async def send(self, agent_name: str, text: str) -> str:
        """Send a one-shot message to an agent (for CLI use)."""
        from .router import InboundMessage

        msg = InboundMessage(agent=agent_name, text=text, source="cli")
        outbound = await self.router.route(msg)
        return outbound.text


def get_log_path(base_dir: Path) -> Path:
    """Return the default log file path for a smolclaw instance."""
    return base_dir / "smolclaw.log"


def setup_logging(base_dir: Path, level: str = "INFO") -> None:
    """Configure logging to both stdout and a log file."""
    log_fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"
    log_level = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger("smolclaw")
    root.setLevel(log_level)

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(log_fmt, datefmt=date_fmt))
    root.addHandler(console)

    # File handler (rotating at 5 MB, keep 3 backups)
    from logging.handlers import RotatingFileHandler

    log_file = get_log_path(base_dir)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(log_fmt, datefmt=date_fmt))
    root.addHandler(file_handler)


async def run_gateway(base_dir: Path, with_api: bool = True) -> None:
    """Main entry point — run the gateway with optional API server."""
    config = load_gateway_config(base_dir)
    setup_logging(base_dir, level=config.log_level)

    gw = Gateway(base_dir)
    try:
        await gw.start()
    except Exception as e:
        log.critical(f"Gateway failed to start: {e}")
        raise

    # Start API server if requested
    api_task = None
    if with_api:
        try:
            import uvicorn

            from .api import create_app

            app = create_app(gw)
            config = uvicorn.Config(
                app,
                host=gw.config.host,
                port=gw.config.port,
                log_level="warning",
            )
            server = uvicorn.Server(config)
            api_task = asyncio.create_task(server.serve())
            log.info(f"API server: http://{gw.config.host}:{gw.config.port}")
            if gw.config.api_key:
                log.info("API authentication: enabled (Bearer token)")
            else:
                log.warning(
                    "API authentication: disabled — set api_key in config.yaml "
                    "or run 'smolclaw config set api_key <key>'"
                )
        except ImportError:
            log.warning("FastAPI/uvicorn not installed — API disabled")

    # Wait for shutdown signal
    stop_event = asyncio.Event()

    def handle_signal():
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)

    version_line = f"smolclaw gateway v{__version__}"
    padded = version_line.center(40)
    print(
        "╔══════════════════════════════════════════╗\n"
        f"║ {padded} ║\n"
        "╠══════════════════════════════════════════╣\n"
        f"║  Agents:  {len(gw.agents):<29}║\n"
        f"║  Channels: {len(gw.channels):<28}║\n"
        f"║  API:     http://{gw.config.host}:{gw.config.port:<14}    ║\n"
        "╚══════════════════════════════════════════╝"
    )

    await stop_event.wait()
    await gw.stop()

    if api_task:
        api_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await api_task
