-- Fix: agent_health_1m and pr_cost_hourly were created without explicitly enabling
-- real-time aggregation, and Tiger Cloud's TimescaleDB defaults continuous aggregates to
-- materialized_only = true - meaning a query only sees refreshed buckets, not raw rows
-- written since the last refresh. With the original policy (start_offset => 2 hours,
-- refresh every 1 minute), a query could lag the true total by up to ~2 hours.
--
-- Discovered in Phase 16 while building economics/budget.py: BudgetGuard reads
-- agent_health_1m for "today's spend so far" and must see a cost_usd write immediately,
-- not after a refresh cycle - a budget guard that lags cannot actually cap runaway
-- spend before it happens. Verified empirically: a fresh write's cost_usd was
-- immediately visible in raw agent_events but not in agent_health_1m until this fix.
--
-- ALTER MATERIALIZED VIEW ... SET is idempotent - safe to re-run.

ALTER MATERIALIZED VIEW agent_health_1m
    SET (timescaledb.materialized_only = false);

ALTER MATERIALIZED VIEW pr_cost_hourly
    SET (timescaledb.materialized_only = false);
