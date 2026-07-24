"""Retry-with-backoff wrapper applied to the GitHub client and LLM client calls
(ARCHITECTURE L8). An async decorator: retries a coroutine function on a configurable
set of exception types with exponential backoff + full jitter, giving up after
max_attempts and re-raising the last error for the caller (or a wrapping
circuit_breaker.py) to handle.

Only retry_on-listed exceptions are retried - a 400 (malformed request) will never
succeed on retry and should fail fast, but a rate limit (429) or a transient network
error usually will."""

from __future__ import annotations

import asyncio
import logging
import random
from functools import wraps
from typing import Awaitable, Callable, ParamSpec, TypeVar

logger = logging.getLogger("reliability.retry")

P = ParamSpec("P")
R = TypeVar("R")


def with_retry(
    *,
    max_attempts: int = 3,
    base_delay_s: float = 0.5,
    max_delay_s: float = 8.0,
    retry_on: tuple[type[Exception], ...] = (Exception,),
):
    """Retry an async function with exponential backoff + full jitter (delay is chosen
    uniformly in [0, min(max_delay_s, base_delay_s * 2**(attempt-1))]) - jitter avoids
    every concurrent caller retrying in lockstep and re-triggering the same rate limit
    together. Re-raises the last exception after max_attempts."""

    def decorator(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await fn(*args, **kwargs)
                except retry_on as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        break
                    delay = random.uniform(0, min(max_delay_s, base_delay_s * (2 ** (attempt - 1))))
                    logger.warning(
                        "retry %d/%d for %s after %s: backing off %.2fs",
                        attempt, max_attempts, fn.__qualname__, exc, delay,
                    )
                    await asyncio.sleep(delay)
            assert last_exc is not None
            raise last_exc
        return wrapper
    return decorator
