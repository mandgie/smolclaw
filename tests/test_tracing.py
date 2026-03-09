"""Tests for the OpenTelemetry tracing module."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from smolclaw.tracing import (
    TRACING_AVAILABLE,
    TracingConfig,
    _NoOpSpan,
    _NoOpTracer,
    configure_tracing,
    get_tracer,
    set_span_attribute,
    span,
    trace_cron_job,
    trace_llm_call,
    trace_memory_op,
    trace_route,
)


class TestTracingConfig:
    def test_defaults(self):
        cfg = TracingConfig()
        assert cfg.enabled is False
        assert cfg.service_name == "smolclaw"
        assert cfg.exporter == "console"
        assert cfg.endpoint == ""

    def test_custom(self):
        cfg = TracingConfig(
            enabled=True,
            service_name="myapp",
            exporter="otlp",
            endpoint="http://localhost:4318/v1/traces",
        )
        assert cfg.enabled is True
        assert cfg.service_name == "myapp"
        assert cfg.exporter == "otlp"
        assert cfg.endpoint == "http://localhost:4318/v1/traces"


class TestConfigureTracing:
    def test_returns_false_when_disabled(self):
        cfg = TracingConfig(enabled=False)
        assert configure_tracing(cfg) is False

    def test_returns_false_when_none(self):
        assert configure_tracing(None) is False

    @pytest.mark.skipif(not TRACING_AVAILABLE, reason="opentelemetry not installed")
    def test_configure_console_exporter(self):
        """When OTEL is installed, configure with console exporter."""
        import smolclaw.tracing as tracing_mod

        # Reset module state
        tracing_mod._configured = False
        try:
            cfg = TracingConfig(enabled=True, exporter="console")
            result = configure_tracing(cfg)
            assert result is True
            assert tracing_mod._configured is True
        finally:
            tracing_mod._configured = False

    @pytest.mark.skipif(not TRACING_AVAILABLE, reason="opentelemetry not installed")
    def test_configure_idempotent(self):
        """Second call returns True without re-configuring."""
        import smolclaw.tracing as tracing_mod

        tracing_mod._configured = False
        try:
            cfg = TracingConfig(enabled=True)
            configure_tracing(cfg)
            # Second call should return True (already configured)
            assert configure_tracing(cfg) is True
        finally:
            tracing_mod._configured = False

    @pytest.mark.skipif(not TRACING_AVAILABLE, reason="opentelemetry not installed")
    def test_configure_otlp_without_package(self):
        """OTLP exporter falls back to console if otlp package missing."""
        import smolclaw.tracing as tracing_mod

        tracing_mod._configured = False
        try:
            modules_patch = {
                "opentelemetry.exporter.otlp.proto.http.trace_exporter": None,
            }
            with patch.dict("sys.modules", modules_patch):
                cfg = TracingConfig(enabled=True, exporter="otlp", endpoint="http://localhost:4318")
                # Should not raise — falls back to console
                result = configure_tracing(cfg)
                assert result is True
        finally:
            tracing_mod._configured = False


class TestGetTracer:
    def test_returns_tracer(self):
        tracer = get_tracer("test")
        assert tracer is not None

    def test_returns_noop_when_unavailable(self):
        """When OTEL is not available, returns a _NoOpTracer."""
        import smolclaw.tracing as tracing_mod

        original = tracing_mod.TRACING_AVAILABLE
        tracing_mod.TRACING_AVAILABLE = False
        try:
            tracer = get_tracer()
            assert isinstance(tracer, _NoOpTracer)
        finally:
            tracing_mod.TRACING_AVAILABLE = original


class TestSpanContextManager:
    def test_span_noop_when_not_configured(self):
        """span() yields None when tracing is not configured."""
        import smolclaw.tracing as tracing_mod

        original_configured = tracing_mod._configured
        tracing_mod._configured = False
        try:
            with span("test.op", {"key": "value"}) as s:
                assert s is None
        finally:
            tracing_mod._configured = original_configured

    def test_span_noop_when_unavailable(self):
        """span() yields None when OTEL is not installed."""
        import smolclaw.tracing as tracing_mod

        original = tracing_mod.TRACING_AVAILABLE
        tracing_mod.TRACING_AVAILABLE = False
        try:
            with span("test.op") as s:
                assert s is None
        finally:
            tracing_mod.TRACING_AVAILABLE = original

    @pytest.mark.skipif(not TRACING_AVAILABLE, reason="opentelemetry not installed")
    def test_span_creates_real_span_when_configured(self):
        """When configured, span() creates and yields a real OTEL span."""
        import smolclaw.tracing as tracing_mod

        tracing_mod._configured = False
        try:
            cfg = TracingConfig(enabled=True)
            configure_tracing(cfg)

            with span("test.operation", {"test.key": "val"}) as s:
                assert s is not None
                s.set_attribute("extra", 42)
        finally:
            tracing_mod._configured = False

    @pytest.mark.skipif(not TRACING_AVAILABLE, reason="opentelemetry not installed")
    def test_span_records_exception(self):
        """Exceptions propagate and are recorded on the span."""
        import smolclaw.tracing as tracing_mod

        tracing_mod._configured = False
        try:
            cfg = TracingConfig(enabled=True)
            configure_tracing(cfg)

            with pytest.raises(ValueError, match="boom"):
                with span("test.error"):
                    raise ValueError("boom")
        finally:
            tracing_mod._configured = False


class TestSpanHelpers:
    def test_trace_route_returns_context_manager(self):
        ctx = trace_route("tars", "telegram", "hello world")
        with ctx:
            pass

    def test_trace_llm_call_returns_context_manager(self):
        ctx = trace_llm_call("tars", "claude-opus-4-6", "hello")
        with ctx:
            pass

    def test_trace_memory_op_returns_context_manager(self):
        ctx = trace_memory_op("tars", "search_facts", "query")
        with ctx:
            pass

    def test_trace_memory_op_without_query(self):
        ctx = trace_memory_op("tars", "add_fact")
        with ctx:
            pass

    def test_trace_cron_job_returns_context_manager(self):
        ctx = trace_cron_job("morning-briefing", "tars")
        with ctx:
            pass


class TestSetSpanAttribute:
    def test_noop_when_not_configured(self):
        """Should not raise when tracing is not configured."""
        import smolclaw.tracing as tracing_mod

        original = tracing_mod._configured
        tracing_mod._configured = False
        try:
            set_span_attribute("key", "value")
        finally:
            tracing_mod._configured = original

    def test_noop_when_unavailable(self):
        """Should not raise when OTEL is not installed."""
        import smolclaw.tracing as tracing_mod

        original = tracing_mod.TRACING_AVAILABLE
        tracing_mod.TRACING_AVAILABLE = False
        try:
            set_span_attribute("key", "value")
        finally:
            tracing_mod.TRACING_AVAILABLE = original


class TestNoOpTracer:
    def test_start_as_current_span(self):
        tracer = _NoOpTracer()
        with tracer.start_as_current_span("test") as s:
            assert isinstance(s, _NoOpSpan)

    def test_noop_span_methods(self):
        s = _NoOpSpan()
        s.set_attribute("key", "value")
        s.set_status("OK")
        s.record_exception(RuntimeError("test"))


class TestTracingAvailableFlag:
    def test_flag_is_boolean(self):
        assert isinstance(TRACING_AVAILABLE, bool)


class TestPublicExports:
    """Verify tracing is exported from the main package."""

    def test_tracing_in_init(self):
        import smolclaw

        assert hasattr(smolclaw, "TRACING_AVAILABLE")
        assert hasattr(smolclaw, "TracingConfig")
        assert hasattr(smolclaw, "configure_tracing")
        assert hasattr(smolclaw, "span")
