"""A ContextVar-based review_id + span stack, so deeply nested code (retrieval, the LLM
client, tracing.py) can know "what review/span am I part of" without every function in
between threading review_id/span_id through its signature by hand. events.py and
tracing.py both read from this by default.

Safe under LangGraph's concurrent specialist fan-out: asyncio.Task copies the current
context at creation, so each specialist's own span stack is isolated from its siblings,
while review_id (set once per node, at the top of run_specialist/aggregate) never leaks
across concurrent tasks."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_review_id: ContextVar[str | None] = ContextVar("review_id", default=None)
_span_stack: ContextVar[tuple[str, ...]] = ContextVar("span_stack", default=())


def set_review_id(review_id: str) -> None:
    _review_id.set(review_id)


def get_review_id() -> str | None:
    return _review_id.get()


def current_span_id() -> str | None:
    stack = _span_stack.get()
    return stack[-1] if stack else None


@contextmanager
def span(span_id: str | None = None) -> Iterator[tuple[str, str | None]]:
    """Push a new span for the duration of the `with` block. Its parent is whatever span
    was current when entered (or None at the top level). Yields (span_id, parent_span_id)
    so the caller can pass both explicitly to emit_agent_event()/traced_span()."""
    sid = span_id or str(uuid.uuid4())
    parent = current_span_id()
    token = _span_stack.set(_span_stack.get() + (sid,))
    try:
        yield sid, parent
    finally:
        _span_stack.reset(token)
