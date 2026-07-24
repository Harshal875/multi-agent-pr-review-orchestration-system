"""Hard timeout applied to every orchestrator node so the aggregator can never wait
forever on one stalled agent. On timeout, logs and returns `default` (a dict merged
into graph state) instead of raising - a stalled node degrades the review the same way
any other specialist failure does (base_agent.py already treats zero findings as a
normal outcome), it never hangs the graph.

wait_for only intercepts asyncio.TimeoutError - a "real" exception the wrapped node
raises on its own (e.g. the Phase 4 test's injected FAIL_AT_AGGREGATE crash) still
propagates normally; this decorator only changes behavior when the node genuinely
doesn't finish in time."""

from __future__ import annotations

import asyncio
import logging
from functools import wraps
from typing import Awaitable, Callable, ParamSpec, TypeVar

logger = logging.getLogger("reliability.timeout")

P = ParamSpec("P")
R = TypeVar("R")


def with_timeout(seconds: float, *, default: R):
    def decorator(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return await asyncio.wait_for(fn(*args, **kwargs), timeout=seconds)
            except asyncio.TimeoutError:
                logger.warning(
                    "node %s timed out after %.1fs - degrading, not hanging",
                    fn.__qualname__, seconds,
                )
                return default
        return wrapper
    return decorator
