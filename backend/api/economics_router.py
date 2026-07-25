"""REST endpoints exposing cost from the continuous aggregates (agent_health_1m,
pr_cost_hourly) and the daily budget state - consumed by the frontend economics page.
Built in Phase 16, endpoint surface added alongside the frontend (Phase 2/17)."""

from __future__ import annotations

from fastapi import APIRouter

from backend.config import settings
from backend.economics.budget import BudgetGuard
from backend.economics.cost_repository import get_recent_review_costs

router = APIRouter(prefix="/economics", tags=["economics"])


@router.get("/summary")
async def summary():
    status = await BudgetGuard.check()
    return {
        "today_cost_usd": status.spent_usd,
        "daily_cap_usd": status.cap_usd,
        "blocked": status.blocked,
        "confidence_threshold": settings.confidence_threshold,
    }


@router.get("/reviews")
async def review_costs(limit: int = 20):
    return await get_recent_review_costs(limit)
