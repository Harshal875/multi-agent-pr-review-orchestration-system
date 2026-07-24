"""BudgetGuard.check() - called at the top of every agent run in base_agent.py;
hard-blocks further LLM calls once the daily cap (DAILY_BUDGET_USD) is exceeded.

This is a soft, best-effort gate, not a transactional reservation system: the four
specialists in one review's fan-out each read today's running cost independently and
concurrently, so a handful of calls right at the threshold in the same superstep can all
observe "not yet over" and proceed together before the next one sees the tripped cap.
That's an accepted tradeoff for a personal-project cost guard - the alternative (a
distributed lock / reservation per call) is real engineering weight for a threshold that
exists to catch runaway spend, not to enforce a cent-exact ceiling."""

from __future__ import annotations

from dataclasses import dataclass

from backend.config import settings
from backend.economics.cost_repository import get_today_cost_usd


@dataclass
class BudgetStatus:
    spent_usd: float
    cap_usd: float
    blocked: bool


class BudgetGuard:
    @staticmethod
    async def check() -> BudgetStatus:
        spent = await get_today_cost_usd()
        cap = settings.daily_budget_usd
        return BudgetStatus(spent_usd=spent, cap_usd=cap, blocked=spent >= cap)
