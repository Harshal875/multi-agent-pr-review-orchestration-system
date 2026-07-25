"""Read-only queries joining agent_events and finding_records to answer, for any
finding, what was retrieved / what prompt-model ran / what confidence resulted. Exposed
via GET /reviews/{id}/audit (api/reviews.py).

finding_records and agent_events are both regular tables in the same Tiger database
(different Python drivers elsewhere - SQLAlchemy for the truth lane, asyncpg for the
time lane - but the same physical Postgres), so the "join" ROADMAP asks for is a real
SQL JOIN here, not two separate queries merged in Python: one finding_records row
matched against every agent_events row from the specialist (agent_type = agent) that
produced it within that review - span.start/span.end, retrieval, tool.call, llm.call -
giving the complete provenance for that finding in one response."""

from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg

from backend.config import settings
from backend.database.asyncpg_dsn import dsn_and_ssl

_pool: asyncpg.Pool | None = None


async def _pool_() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        dsn, ctx = dsn_and_ssl(settings.tiger_database_url)
        _pool = await asyncpg.create_pool(dsn=dsn, ssl=ctx, min_size=1, max_size=5)
    return _pool


async def get_review_audit(review_id: uuid.UUID) -> list[dict[str, Any]]:
    """For every finding in a review, return the finding plus its full agent_events
    trail (in chronological order) - "why did the agent say this?" answerable from this
    response alone, no code-reading required."""
    pool = await _pool_()
    rows = await pool.fetch(
        """
        SELECT f.id AS finding_id, f.agent_type, f.severity, f.category, f.summary,
               f.file_path, f.line_start, f.line_end, f.suggestion, f.confidence,
               f.rationale, f.created_at AS finding_created_at,
               e.ts, e.event_type, e.model, e.tokens_in, e.tokens_out, e.cost_usd,
               e.latency_ms, e.outcome, e.confidence AS event_confidence, e.payload
        FROM finding_records f
        JOIN agent_events e ON e.review_id = f.review_id AND e.agent = f.agent_type
        WHERE f.review_id = $1
        ORDER BY f.id, e.ts
        """,
        review_id,
    )

    findings: dict[str, dict[str, Any]] = {}
    for r in rows:
        fid = str(r["finding_id"])
        if fid not in findings:
            findings[fid] = {
                "finding_id": fid,
                "agent_type": r["agent_type"],
                "severity": r["severity"],
                "category": r["category"],
                "summary": r["summary"],
                "file_path": r["file_path"],
                "line_start": r["line_start"],
                "line_end": r["line_end"],
                "suggestion": r["suggestion"],
                "confidence": float(r["confidence"]),
                "rationale": r["rationale"],
                "created_at": r["finding_created_at"].isoformat(),
                "trail": [],
            }
        findings[fid]["trail"].append(
            {
                "ts": r["ts"].isoformat(),
                "event_type": r["event_type"],
                "model": r["model"],
                "tokens_in": r["tokens_in"],
                "tokens_out": r["tokens_out"],
                "cost_usd": float(r["cost_usd"]) if r["cost_usd"] is not None else None,
                "latency_ms": r["latency_ms"],
                "outcome": r["outcome"],
                "confidence": (
                    float(r["event_confidence"])
                    if r["event_confidence"] is not None else None
                ),
                "payload": json.loads(r["payload"]) if r["payload"] else None,
            }
        )
    return list(findings.values())
