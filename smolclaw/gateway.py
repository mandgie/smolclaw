"""Gateway — single process that boots all agents, channels, scheduler, and API."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path

from .agent import Agent
from .channel import Channel, create_channel
from .config import (
    GatewayConfig,
    discover_all_agents,
    load_gateway_config,
    load_shared_user_md,
)
from .memory import Memory
from .router import Router
from .scheduler import Job, Scheduler

log = logging.getLogger("smolclaw")


class Gateway:
    """The smolclaw gateway — single process running everything."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.config: GatewayConfig = load_gateway_config(base_dir)
        self.router = Router()
        self.agents: dict[str, Agent] = {}
        self.channels: list[Channel] = []
        self.scheduler: Scheduler | None = None
        self._user_md = ""

    async def start(self):
        """Boot everything: agents, channels, scheduler."""
        log.info(f"smolclaw gateway starting (base={self.base_dir})")

        # Load shared context
        self._user_md = load_shared_user_md(self.base_dir)

        # Discover and load agents
        agents_dir = self.base_dir / self.config.agents_dir
        agent_infos = discover_all_agents(self.base_dir)
        memory_db = self.base_dir / self.config.shared_dir / "memory.db"

        for name, info in agent_infos.items():
            agent = Agent(info, user_md=self._user_md)

            # Attach namespaced memory
            agent.memory = Memory(memory_db, agent=name)

            self.agents[name] = agent
            self.router.register_agent(agent)
            log.info(f"Loaded agent: {name} (model={info.config.model})")

        # Load channel env files and start channels
        for name, agent in self.agents.items():
            # Load env files from agent's channels/ directory
            channels_dir = agent.info.path / "channels"
            if channels_dir.exists():
                for env_file in channels_dir.glob("*.env"):
                    for line in env_file.read_text().splitlines():
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, _, value = line.partition("=")
                            os.environ.setdefault(key.strip(), value.strip())

            for ch_type, ch_config in agent.info.config.channels.items():
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

        agent_count = len(self.agents)
        channel_count = len(self.channels)
        job_count = len(self.scheduler.jobs) if self.scheduler else 0

        log.info(
            f"smolclaw gateway ready: "
            f"{agent_count} agents, {channel_count} channels, {job_count} jobs"
        )

    async def _deliver_cron(self, job: Job, text: str) -> None:
        """Deliver cron job output to the right channel."""
        for channel in self.channels:
            if channel.agent_name == job.agent and channel.channel_type == job.delivery:
                await channel.send(job.delivery_chat_id, text)
                return
        log.warning(f"No {job.delivery} channel found for agent {job.agent}")

    async def stop(self):
        """Graceful shutdown."""
        log.info("smolclaw gateway shutting down")

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


async def run_gateway(base_dir: Path, with_api: bool = True):
    """Main entry point — run the gateway with optional API server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    gw = Gateway(base_dir)
    await gw.start()

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
        except ImportError:
            log.warning("FastAPI/uvicorn not installed — API disabled")

    # Wait for shutdown signal
    stop_event = asyncio.Event()

    def handle_signal():
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)

    print(
        "╔══════════════════════════════════════════╗\n"
        "║         smolclaw gateway v0.1.0          ║\n"
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
        try:
            await api_task
        except asyncio.CancelledError:
            pass
