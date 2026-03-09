"""Optional OpenTelemetry tracing — zero overhead when not installed.

When the ``opentelemetry-api`` and ``opentelemetry-sdk`` packages are installed,
this module configures a TracerProvider and exposes span helpers for core
smolclaw operations (routing, LLM calls, memory, scheduling).

When the packages are absent, all public functions are safe no-ops — the rest
of the codebase can call them unconditionally.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Generator

log = logging.getLogger("smolclaw")

__all__ = [
    "configure_tracing",
    "get_tracer",
    "span",
    "TracingConfig",
    "TRACING_AVAILABLE",
]

# ---------------------------------------------------------------------------
# Detect availability
# ---------------------------------------------------------------------------

try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SimpleSpanProcessor,
    )
    from opentelemetry.trace import StatusCode

    TRACING_AVAILABLE = True
except ImportError:
    TRACING_AVAILABLE = False

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TracingConfig:
    """Lightweight config container for tracing options."""

    def __init__(
        self,
        enabled: bool = False,
        service_name: str = "smolclaw",
        exporter: str = "console",
        endpoint: str = "",
    ):
        self.enabled = enabled
        self.service_name = service_name
        self.exporter = exporter  # "console" | "otlp"
        self.endpoint = endpoint  # for OTLP exporter


# Keep a module-level flag so instrumentation can short-circuit cheaply.
_configured = False
_tracer_name = "smolclaw"


def configure_tracing(config: TracingConfig | None = None) -> bool:
    """Set up the OTEL TracerProvider. Returns True if tracing is active."""
    global _configured

    if _configured:
        return True

    if not TRACING_AVAILABLE:
        log.debug("OpenTelemetry not installed — tracing disabled")
        return False

    if config is None or not config.enabled:
        return False

    resource = Resource.create(
        {
            "service.name": config.service_name,
            "service.version": _get_version(),
        }
    )
    provider = TracerProvider(resource=resource)

    if config.exporter == "otlp" and config.endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=config.endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            log.info(f"Tracing: OTLP exporter → {config.endpoint}")
        except ImportError:
            log.warning(
                "opentelemetry-exporter-otlp-proto-http not installed, "
                "falling back to console exporter"
            )
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    else:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        log.info("Tracing: console exporter")

    trace.set_tracer_provider(provider)
    _configured = True
    log.info("Tracing: configured")
    return True


def get_tracer(name: str | None = None) -> Any:
    """Return an OTEL Tracer (or a no-op stand-in)."""
    if TRACING_AVAILABLE:
        return trace.get_tracer(name or _tracer_name)
    return _NoOpTracer()


# ---------------------------------------------------------------------------
# Span helper — the main interface used by other modules
# ---------------------------------------------------------------------------


@contextmanager
def span(
    name: str,
    attributes: dict[str, Any] | None = None,
    kind: str = "internal",
) -> Generator[Any, None, None]:
    """Context manager that creates an OTEL span (or no-ops).

    Usage::

        with span("agent.send", {"agent.name": "tars", "gen_ai.request.model": "opus"}):
            result = await agent.send(text)
    """
    if not TRACING_AVAILABLE or not _configured:
        yield None
        return

    tracer = trace.get_tracer(_tracer_name)

    kind_map = {
        "internal": trace.SpanKind.INTERNAL,
        "client": trace.SpanKind.CLIENT,
        "server": trace.SpanKind.SERVER,
        "producer": trace.SpanKind.PRODUCER,
        "consumer": trace.SpanKind.CONSUMER,
    }
    span_kind = kind_map.get(kind, trace.SpanKind.INTERNAL)

    with tracer.start_as_current_span(name, kind=span_kind) as s:
        if attributes:
            for k, v in attributes.items():
                s.set_attribute(k, v)
        try:
            yield s
        except Exception as exc:
            s.set_status(StatusCode.ERROR, str(exc))
            s.record_exception(exc)
            raise


# ---------------------------------------------------------------------------
# Instrumentation helpers for specific subsystems
# ---------------------------------------------------------------------------


def trace_route(agent_name: str, source: str, text: str) -> Any:
    """Create a span for message routing."""
    return span(
        "smolclaw.route",
        attributes={
            "smolclaw.agent": agent_name,
            "smolclaw.source": source,
            "smolclaw.message.length": len(text),
        },
        kind="server",
    )


def trace_llm_call(agent_name: str, model: str, text: str) -> Any:
    """Create a span for an LLM call (GenAI semantic conventions)."""
    return span(
        "gen_ai.chat",
        attributes={
            "gen_ai.system": "anthropic",
            "gen_ai.request.model": model,
            "gen_ai.operation.name": "chat",
            "smolclaw.agent": agent_name,
            "smolclaw.prompt.length": len(text),
        },
        kind="client",
    )


def trace_memory_op(agent_name: str, operation: str, query: str = "") -> Any:
    """Create a span for a memory operation."""
    attrs: dict[str, Any] = {
        "smolclaw.agent": agent_name,
        "smolclaw.memory.operation": operation,
    }
    if query:
        attrs["smolclaw.memory.query.length"] = len(query)
    return span(f"smolclaw.memory.{operation}", attributes=attrs)


def trace_cron_job(job_id: str, agent_name: str) -> Any:
    """Create a span for a cron job execution."""
    return span(
        "smolclaw.cron.execute",
        attributes={
            "smolclaw.cron.job_id": job_id,
            "smolclaw.agent": agent_name,
        },
        kind="consumer",
    )


def set_span_attribute(key: str, value: Any) -> None:
    """Set an attribute on the current active span (no-op if tracing disabled)."""
    if not TRACING_AVAILABLE or not _configured:
        return
    current = trace.get_current_span()
    if current:
        current.set_attribute(key, value)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_version() -> str:
    try:
        from . import __version__

        return __version__
    except Exception:
        return "unknown"


class _NoOpTracer:
    """Minimal stand-in when opentelemetry isn't installed."""

    @contextmanager
    def start_as_current_span(self, *args: Any, **kwargs: Any) -> Generator:
        yield _NoOpSpan()


class _NoOpSpan:
    """Minimal stand-in span."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, *args: Any, **kwargs: Any) -> None:
        pass

    def record_exception(self, exc: Exception) -> None:
        pass
