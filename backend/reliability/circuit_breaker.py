"""Circuit breaker for external calls (GitHub API, LLM provider) so a stalled
dependency degrades gracefully instead of the pipeline hammering it forever. Three
states: CLOSED (normal) -> OPEN (fail fast, no calls through) after enough consecutive
failures -> HALF_OPEN (one probe call allowed) once the cooldown elapses. A successful
probe closes the circuit again; a failed probe reopens it.

One CircuitBreaker instance per external dependency (e.g. one for the Groq LLM client),
shared across all concurrent callers - that's what makes "consecutive failures" a
meaningful signal rather than per-call noise."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Awaitable, Callable, ParamSpec, TypeVar

logger = logging.getLogger("reliability.circuit_breaker")

P = ParamSpec("P")
R = TypeVar("R")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised instead of calling through when the breaker is OPEN (still cooling down)."""


@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 5
    cooldown_s: float = 30.0
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _opened_at: float = field(default=0.0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def _before_call(self) -> None:
        async with self._lock:
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._opened_at >= self.cooldown_s:
                    self._state = CircuitState.HALF_OPEN
                    logger.info("circuit=%s HALF_OPEN: cooldown elapsed, probing", self.name)
                else:
                    raise CircuitOpenError(f"circuit '{self.name}' is open")

    async def _on_success(self) -> None:
        async with self._lock:
            if self._state != CircuitState.CLOSED:
                logger.info("circuit=%s CLOSED: probe succeeded", self.name)
            self._state = CircuitState.CLOSED
            self._failure_count = 0

    async def _on_failure(self) -> None:
        async with self._lock:
            self._failure_count += 1
            if self._state == CircuitState.HALF_OPEN or self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                logger.warning(
                    "circuit=%s OPEN: %d consecutive failures", self.name, self._failure_count
                )

    def wrap(self, fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            await self._before_call()
            try:
                result = await fn(*args, **kwargs)
            except Exception:
                await self._on_failure()
                raise
            else:
                await self._on_success()
                return result
        return wrapper
