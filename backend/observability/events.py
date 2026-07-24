"""emit_agent_event() - writes one row per action (span start/end, llm.call, tool.call,
decision) into the agent_events hypertable (scripts/migrations/2026-06-tiger-init.sql).
The single write path feeding the trace viewer (Phase 15's audit endpoint), the
agent_health_1m / pr_cost_hourly continuous aggregates, and the cost ledger.

review_id/span_id/parent_span default to the ambient workflow_context so call sites in
base_agent.py stay terse; pass them explicitly to override. A write failure is logged and
swallowed, never raised - observability must not be able to fail a review (the same
reliability posture as retrieval and tool-call handling in base_agent.py)."""

from __future__ import annotations

import json
import logging
import uuid

import asyncpg

from backend.config import settings
from backend.database.asyncpg_dsn import dsn_and_ssl
from backend.observability import workflow_context

logger = logging.getLogger("observability.events")

# Approximate Groq on-demand pricing (USD per 1M tokens, input/output). Verify current
# rates at console.groq.com/settings/billing before trusting these for real billing
# decisions - this is a directional cost signal for the trace viewer, not an invoice.
_PRICING_PER_1M: dict[str, tuple[float, float]] = {
    "openai/gpt-oss-120b": (0.15, 0.75),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "llama-3.3-70b-versatile": (0.59, 0.79),
}


def estimate_cost_usd(model: str, tokens_in: int, tokens_out: int) -> float | None:
    rates = _PRICING_PER_1M.get(model)
    if rates is None:
        return None
    price_in, price_out = rates
    return round(tokens_in / 1_000_000 * price_in + tokens_out / 1_000_000 * price_out, 6)


_pool: asyncpg.Pool | None = None


async def _pool_() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        dsn, ctx = dsn_and_ssl(settings.tiger_database_url)
        _pool = await asyncpg.create_pool(dsn=dsn, ssl=ctx, min_size=1, max_size=5)
    return _pool


async def emit_agent_event(
    agent: str,
    event_type: str,
    *,
    review_id: str | None = None,
    span_id: str | None = None,
    parent_span: str | None = None,
    model: str | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    cost_usd: float | None = None,
    latency_ms: int | None = None,
    outcome: str | None = None,
    confidence: float | None = None,
    payload: dict | None = None,
) -> None:
    review_id = review_id or workflow_context.get_review_id()
    span_id = span_id or workflow_context.current_span_id() or str(uuid.uuid4())
    if review_id is None:
        logger.warning(
            "emit_agent_event: no review_id (agent=%s event_type=%s) - dropping event",
            agent, event_type,
        )
        return

    try:
        pool = await _pool_()
        await pool.execute(
            """
            INSERT INTO agent_events
                (ts, review_id, agent, span_id, parent_span, event_type, model,
                 tokens_in, tokens_out, cost_usd, latency_ms, outcome, confidence, payload)
            VALUES
                (now(), $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13::jsonb)
            """,
            uuid.UUID(review_id), agent, uuid.UUID(span_id),
            uuid.UUID(parent_span) if parent_span else None,
            event_type, model, tokens_in, tokens_out, cost_usd, latency_ms, outcome,
            confidence, json.dumps(payload) if payload is not None else None,
        )
    except Exception as exc:  # noqa: BLE001 - observability must never fail a review
        logger.warning(
            "emit_agent_event failed (agent=%s event_type=%s): %s", agent, event_type, exc
        )
