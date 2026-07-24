"""Phase 12 DoD: point the LLM client at an invalid URL temporarily - the system retries
with backoff, then fails that node gracefully, and the review still completes with 3/4
agents' findings rather than hanging forever.

Two parts, because llm_client's OpenAI client is a shared singleton (breaking it breaks
every agent, not just one) - each part isolates one clause of the DoD sentence honestly
rather than forcing one artificial scenario to cover both:

  Part 1 - "retries with backoff": point a throwaway client at an unreachable URL and
  call complete_async() directly; measure that failure takes meaningfully longer than a
  single attempt would (proving backoff delays actually elapsed), and that it raises
  rather than hanging.

  Part 2 - "fails that node gracefully, review still completes with 3/4 agents' findings,
  not hanging forever": override just the security agent's route (tools/model_router,
  Phase 5's set_route()) to a nonexistent model, run the FULL graph against Phase 8's
  real planted-SQL-injection diff, and confirm security contributes zero findings while
  quality/tests/docs contribute real ones and the graph completes in bounded time.

Run: python scripts/phase12_reliability_test.py
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scripts.phase8_agents_test import PLANTED_DIFF, REPO  # noqa: E402


async def part1_retry_with_backoff() -> bool:
    from openai import OpenAI

    from backend.reliability.circuit_breaker import CircuitBreaker
    from backend.reliability.retry import with_retry

    # An unroutable loopback port - connection fails fast and reliably, no real network
    # access needed, so this is deterministic in any environment.
    broken_client = OpenAI(api_key="x", base_url="http://127.0.0.1:1/v1")
    breaker = CircuitBreaker(name="test_broken_llm", failure_threshold=99, cooldown_s=999)

    @breaker.wrap
    @with_retry(max_attempts=3, base_delay_s=0.3, max_delay_s=1.0, retry_on=(Exception,))
    async def broken_call():
        return await asyncio.to_thread(
            lambda: broken_client.chat.completions.create(
                model="whatever", messages=[{"role": "user", "content": "hi"}], max_tokens=10,
            )
        )

    t0 = time.monotonic()
    raised = False
    try:
        await broken_call()
    except Exception as exc:  # noqa: BLE001
        raised = True
        print(f"  [part1] after retries exhausted, raised: {type(exc).__name__}")
    elapsed = time.monotonic() - t0

    print(f"  [part1] elapsed={elapsed:.2f}s (3 attempts, min ~2 backoff sleeps of up to 0.3s+0.6s)")
    # 2 backoff sleeps happened (between attempts 1->2 and 2->3), each in [0, min(1.0, 0.3*2^n)]
    # - not a tight guarantee (jitter can roll near 0), but a real multi-attempt loop with
    # any backoff at all reliably takes noticeably longer than one instant failed connection.
    ok = raised and elapsed > 0.05
    print(f"  [part1] retried (not instant single failure) and raised (not hung)? {ok}")
    return ok


async def part2_partial_degradation() -> bool:
    from backend.orchestrator.langgraph_engine import LangGraphEngine
    from backend.tools import model_router
    from backend.models.enums import AgentType

    original_security_model = model_router.model_for(AgentType.SECURITY)
    model_router.set_route(AgentType.SECURITY, "this-model-does-not-exist-xyz123")

    try:
        review_id = str(uuid.uuid4())
        engine = LangGraphEngine()
        initial = {
            "review_id": review_id, "repo": REPO, "pr_number": 998,
            "commit_sha": "phase12-partial-degradation", "diff": PLANTED_DIFF, "findings": [],
        }

        print(f"  [part2 review_id={review_id}] security agent routed at a nonexistent "
              f"model; quality/tests/docs routed normally...")
        t0 = time.monotonic()
        result = await asyncio.wait_for(engine.run(review_id, initial), timeout=120.0)
        elapsed = time.monotonic() - t0

        raw = result.get("findings", [])
        by_agent: dict[str, int] = {}
        for f in raw:
            by_agent[f["agent_type"]] = by_agent.get(f["agent_type"], 0) + 1

        print(f"  [part2] completed in {elapsed:.1f}s (bounded, not hung)")
        print(f"  [part2] findings by agent: {by_agent}")
        print(f"  [part2] decision={result.get('decision')} overall={result.get('overall_confidence')}")

        security_failed_gracefully = by_agent.get("security", 0) == 0
        others_succeeded = sum(v for k, v in by_agent.items() if k != "security") > 0
        graph_completed = result.get("decision") in ("post", "awaiting_human")

        print(f"  [part2] security contributed 0 findings (failed, didn't crash)? {security_failed_gracefully}")
        print(f"  [part2] the other agents contributed real findings? {others_succeeded}")
        print(f"  [part2] graph reached a decision, not hung? {graph_completed}")

        return security_failed_gracefully and others_succeeded and graph_completed
    finally:
        model_router.set_route(AgentType.SECURITY, original_security_model)


async def main() -> int:
    print("=== Part 1: retries with backoff, then fails (not hangs) ===")
    ok1 = await part1_retry_with_backoff()

    print("\n=== Part 2: one node fails gracefully, review still completes with the rest ===")
    ok2 = await part2_partial_degradation()

    ok = ok1 and ok2
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
