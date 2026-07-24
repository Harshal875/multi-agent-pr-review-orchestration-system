"""Phase 16 DoD: set a deliberately low test cap, run a review, and confirm the agent
stops calling the LLM once the cap trips - verified by watching agent_events stop
accumulating llm.call rows.

The four specialists in one review fan out in parallel (Phase 4), not sequentially, so
there's no meaningful "mid-run" moment to watch within a single review - all four read
BudgetGuard at roughly the same instant. Instead this proves the mechanism the DoD cares
about across two reviews: review A runs with a generous cap (llm.call rows accumulate
normally); the cap is then set below the now-accumulated total and review B runs -
confirming ALL FOUR specialists in review B are blocked before making a single LLM call.

Run: python scripts/phase16_budget_test.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scripts.phase8_agents_test import PLANTED_DIFF, REPO  # noqa: E402


async def _count_llm_calls(review_id: str) -> int:
    from backend.observability.events import _pool_

    pool = await _pool_()
    return await pool.fetchval(
        "SELECT count(*) FROM agent_events WHERE review_id = $1 AND event_type = 'llm.call'",
        review_id,
    )


async def _count_budget_exceeded(review_id: str) -> int:
    from backend.observability.events import _pool_

    pool = await _pool_()
    return await pool.fetchval(
        "SELECT count(*) FROM agent_events "
        "WHERE review_id = $1 AND event_type = 'span.end' AND outcome = 'budget_exceeded'",
        review_id,
    )


async def main() -> int:
    from backend.config import settings
    from backend.economics.budget import BudgetGuard
    from backend.economics.cost_repository import get_today_cost_usd
    from backend.orchestrator.langgraph_engine import LangGraphEngine

    original_cap = settings.daily_budget_usd
    engine = LangGraphEngine()

    try:
        baseline = await get_today_cost_usd()
        print(f"baseline spend today (before this test): ${baseline:.6f}")

        # --- Review A: generous cap - normal operation ---
        settings.daily_budget_usd = baseline + 0.10
        status_a = await BudgetGuard.check()
        print(f"\n[Review A] cap=${status_a.cap_usd:.6f} spent=${status_a.spent_usd:.6f} "
              f"blocked={status_a.blocked}")

        review_a = str(uuid.uuid4())
        initial_a = {
            "review_id": review_a, "repo": REPO, "pr_number": 996,
            "commit_sha": "phase16-review-a-normal", "diff": PLANTED_DIFF, "findings": [],
        }
        print(f"[Review A id={review_a}] running full graph normally...")
        result_a = await engine.run(review_a, initial_a)
        llm_calls_a = await _count_llm_calls(review_a)
        print(f"[Review A] llm.call rows written: {llm_calls_a} | "
              f"decision={result_a.get('decision')}")

        # --- Review B: cap now BELOW the just-accumulated total - hard block ---
        after_a = await get_today_cost_usd()
        settings.daily_budget_usd = after_a - 0.0001  # deliberately already tripped
        status_b = await BudgetGuard.check()
        print(f"\n[Review B] spend after A=${after_a:.6f}, cap lowered to "
              f"${settings.daily_budget_usd:.6f} -> blocked={status_b.blocked}")

        review_b = str(uuid.uuid4())
        initial_b = {
            "review_id": review_b, "repo": REPO, "pr_number": 995,
            "commit_sha": "phase16-review-b-blocked", "diff": PLANTED_DIFF, "findings": [],
        }
        print(f"[Review B id={review_b}] running full graph with the tripped cap...")
        result_b = await engine.run(review_b, initial_b)
        llm_calls_b = await _count_llm_calls(review_b)
        budget_exceeded_events = await _count_budget_exceeded(review_b)
        print(f"[Review B] llm.call rows written: {llm_calls_b} | "
              f"budget_exceeded span.end events: {budget_exceeded_events} | "
              f"findings={len(result_b.get('deduped_findings', []))} "
              f"decision={result_b.get('decision')}")

        # --- DoD checks ---
        a_worked_normally = llm_calls_a > 0
        b_made_zero_llm_calls = llm_calls_b == 0
        b_all_four_blocked = budget_exceeded_events == 4
        b_no_findings = len(result_b.get("deduped_findings", [])) == 0

        print(f"\n[DoD] Review A (generous cap) made real LLM calls? {a_worked_normally}")
        print(f"[DoD] Review B (tripped cap) made ZERO LLM calls? {b_made_zero_llm_calls}")
        print(f"[DoD] all 4 specialists in Review B hit budget_exceeded? {b_all_four_blocked}")
        print(f"[DoD] Review B produced no findings (Finding-free result)? {b_no_findings}")

        ok = a_worked_normally and b_made_zero_llm_calls and b_all_four_blocked and b_no_findings
        print("\nRESULT:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        settings.daily_budget_usd = original_cap
        print(f"\n(restored daily_budget_usd to ${original_cap:.2f})")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
