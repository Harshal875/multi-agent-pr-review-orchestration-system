"""Thin wrapper over the reasoning LLM — the single call path every specialist agent uses
(via base_agent). Provider-agnostic by design: agents pass a model string (from
tools/model_router) and get back text + token usage; they never touch the SDK.

Currently backed by Groq (OpenAI-compatible Chat Completions) because the Anthropic and
OpenAI accounts had no credit/quota. The `complete()` signature is deliberately the same
one an Anthropic-backed client would expose, so switching back to Claude later is a
one-file change. `effort`/`thinking` are Anthropic-only knobs and are accepted-but-ignored
here so agent code doesn't have to branch on provider.

complete_async() (Phase 12) is the call every agent should use: it runs complete() in a
thread (keeps the event loop free for concurrent specialists), retries transient failures
(rate limits, timeouts, connection errors, 5xx - never a 400, which will never succeed on
retry) with backoff, and trips a shared circuit breaker after repeated failures so a
genuinely down provider fails fast instead of every specialist hanging on its own
retry loop."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)

from backend.config import settings
from backend.reliability.circuit_breaker import CircuitBreaker
from backend.reliability.retry import with_retry

_client: OpenAI | None = None
_circuit = CircuitBreaker(name="groq_llm", failure_threshold=5, cooldown_s=30.0)
_RETRYABLE = (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError)


def _client_() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.groq_api_key, base_url=settings.groq_base_url)
    return _client


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


def complete(
    *,
    model: str,
    system: str,
    user: str,
    max_tokens: int = 4096,  # gpt-oss-120b spends output tokens on hidden reasoning first
    effort: str | None = None,      # Anthropic-only; ignored on Groq
    thinking: bool = False,         # Anthropic-only; ignored on Groq
) -> LLMResult:
    """One non-streaming completion. Returns text + token usage for cost attribution."""
    resp = _client_().chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    usage = resp.usage
    return LLMResult(
        text=resp.choices[0].message.content or "",
        model=resp.model,
        input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
        output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
    )


@_circuit.wrap
@with_retry(max_attempts=3, base_delay_s=0.5, max_delay_s=8.0, retry_on=_RETRYABLE)
async def complete_async(
    *,
    model: str,
    system: str,
    user: str,
    max_tokens: int = 4096,
    effort: str | None = None,
    thinking: bool = False,
) -> LLMResult:
    """The async, reliability-wrapped call site every agent should use instead of
    complete() directly. Decorator order matters: with_retry runs first (innermost),
    so up to 3 attempts happen before the circuit breaker ever counts a failure -
    a single flaky call shouldn't move the breaker toward OPEN, only a call that fails
    even after retrying should."""
    return await asyncio.to_thread(
        complete, model=model, system=system, user=user, max_tokens=max_tokens,
        effort=effort, thinking=thinking,
    )
