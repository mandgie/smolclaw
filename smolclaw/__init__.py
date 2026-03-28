"""smolclaw — Lightweight multi-agent framework for personal AI assistants."""

__version__ = "0.2.1"

from .agent import Agent
from .channel import (
    TelegramChannel,
    WebhookChannel,
    create_channel,
    list_channel_types,
    register_channel,
)
from .config import AgentConfig, AgentInfo, ChannelConfig, GatewayConfig, MemoryConfig, SkillInfo
from .gateway import Gateway
from .hooks import HookContext, HookRegistry, PostRouteHook, PreRouteHook
from .memory import Memory, serialize_f32
from .router import InboundMessage, OutboundMessage, Router
from .scheduler import Job, Scheduler
from .tracing import TRACING_AVAILABLE, TracingConfig, configure_tracing, span
from .watcher import FileWatcher

__all__ = [
    "TRACING_AVAILABLE",
    "Agent",
    "AgentConfig",
    "AgentInfo",
    "ChannelConfig",
    "FileWatcher",
    "Gateway",
    "GatewayConfig",
    "HookContext",
    "HookRegistry",
    "InboundMessage",
    "Job",
    "Memory",
    "MemoryConfig",
    "OutboundMessage",
    "PostRouteHook",
    "PreRouteHook",
    "Router",
    "Scheduler",
    "SkillInfo",
    "TelegramChannel",
    "TracingConfig",
    "WebhookChannel",
    "__version__",
    "configure_tracing",
    "create_channel",
    "list_channel_types",
    "register_channel",
    "serialize_f32",
    "span",
]
