"""Reads today's running cost from the agent_health_1m continuous aggregate
(scripts/migrations/2026-06-tiger-init.sql) - the same table Phase 10's cost_usd writes
feed. "Today" is a UTC calendar day (date_trunc('day', now())), computed server-side so
it's consistent regardless of the caller's local timezone.

A budget guard is only correct if it sees spend immediately, not after a refresh cycle -
agent_health_1m's original refresh policy (start_offset 2 hours, every 1 minute) could
lag a query by up to ~2 hours if the view only served materialized buckets. It turned out
to: Tiger Cloud created this continuous aggregate with materialized_only = true (contrary
to the "real-time aggregation on by default" assumption this module was first written
against), which was caught empirically while building this module - a fresh cost_usd
write was visible in raw agent_events immediately but invisible here until the next
refresh. Fixed at the source via scripts/migrations/2026-07-realtime-aggregation.sql
(materialized_only = false), not routed around here - the same fix benefits every other
consumer of this view, including pr_cost_hourly's twin bug. See that migration file for
the full story."""

from __future__ import annotations

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


async def get_today_cost_usd() -> float:
    pool = await _pool_()
    total = await pool.fetchval(
        """
        SELECT COALESCE(sum(cost_usd), 0)
        FROM agent_health_1m
        WHERE bucket >= date_trunc('day', now())
        """
    )
    return float(total)


async def get_recent_review_costs(limit: int = 20) -> list[dict]:
    """Per-review cost rollup from the pr_cost_hourly continuous aggregate (Phase 16),
    newest first - powers the frontend economics page."""
    pool = await _pool_()
    rows = await pool.fetch(
        """
        SELECT review_id, sum(total_cost_usd) AS cost_usd,
               max(agents_used) AS agents_used, max(max_confidence) AS max_confidence,
               max(bucket) AS last_bucket
        FROM pr_cost_hourly
        GROUP BY review_id
        ORDER BY last_bucket DESC
        LIMIT $1
        """,
        limit,
    )
    return [
        {
            "review_id": str(r["review_id"]),
            "cost_usd": float(r["cost_usd"]) if r["cost_usd"] is not None else 0.0,
            "agents_used": r["agents_used"],
            "max_confidence": float(r["max_confidence"]) if r["max_confidence"] is not None else None,
            "last_bucket": r["last_bucket"].isoformat() if r["last_bucket"] else None,
        }
        for r in rows
    ]
