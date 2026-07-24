"""Thin wrapper over the reasoning LLM — the single call path every specialist agent uses
(via base_agent). Provider-agnostic by design: agents pass a model string (from
tools/model_router) and get back text + token usage; they never touch the SDK.

Currently backed by Groq (OpenAI-compatible Chat Completions) because the Anthropic and
OpenAI accounts had no credit/quota. The `complete()` signature is deliberately the same
one an Anthropic-backed client would expose, so switching back to Claude later is a
one-file change. `effort`/`thinking` are Anthropic-only knobs and are accepted-but-ignored
here so agent code doesn't have to branch on provider."""

from __future__ import annotations

from dataclasses import dataclass

from openai import OpenAI

from backend.config import settings

_client: OpenAI | None = None


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
