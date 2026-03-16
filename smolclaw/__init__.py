"""smolclaw — Lightweight multi-agent framework for personal AI assistants."""

__version__ = "0.1.0"

from .agent import Agent
from .channel import SlackChannel, TelegramChannel, WebhookChannel
from .config import AgentConfig, AgentInfo, GatewayConfig, MemoryConfig
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
    "SlackChannel",
    "TelegramChannel",
    "TracingConfig",
    "WebhookChannel",
    "__version__",
    "configure_tracing",
    "serialize_f32",
    "span",
]
