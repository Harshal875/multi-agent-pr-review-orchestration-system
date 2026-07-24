"""OpenTelemetry spans wrapping the same boundaries as events.py (span start/end,
llm.call, tool.call, decision), so a standard OTel-compatible backend (Jaeger, Grafana
Tempo, an LangSmith-style OTel ingester, etc.) can be pointed at this later by swapping
the exporter - no changes needed at any call site in base_agent.py or nodes.py.

Registers a real TracerProvider (not the SDK's inert default no-op) with a
ConsoleSpanExporter so spans are actually visible during local development/testing
without needing a collector running. Swap the exporter for OTLP once a real backend
exists; every other line in this file stays the same."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from backend.observability import workflow_context

_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(_provider)

_tracer = trace.get_tracer("pr_review_agent")


@contextmanager
def traced_span(name: str, **attributes) -> Iterator[trace.Span]:
    """Wrap a boundary in an OTel span, tagging it with the ambient review_id so every
    span for one review correlates in whatever backend is configured."""
    with _tracer.start_as_current_span(name) as span:
        review_id = workflow_context.get_review_id()
        if review_id:
            span.set_attribute("review_id", review_id)
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)
        yield span
