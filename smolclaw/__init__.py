"""smolclaw — Lightweight multi-agent framework for personal AI assistants."""

__version__ = "0.1.0"

from .agent import Agent
from .channel import TelegramChannel
from .config import AgentConfig, AgentInfo, GatewayConfig, MemoryConfig
from .gateway import Gateway
from .memory import Memory
from .router import InboundMessage, OutboundMessage, Router
from .scheduler import Job, Scheduler

__all__ = [
    "Agent",
    "AgentConfig",
    "AgentInfo",
    "Gateway",
    "GatewayConfig",
    "InboundMessage",
    "Job",
    "Memory",
    "MemoryConfig",
    "OutboundMessage",
    "Router",
    "Scheduler",
    "TelegramChannel",
    "__version__",
]
