"""Phase 10 DoD: SELECT * FROM agent_events WHERE review_id = $1 ORDER BY ts reconstructs
a complete, readable timeline of one full review end-to-end, including cost and latency
per LLM call.

Reuses Phase 8's planted-SQL-injection diff so this run produces real Groq calls (real
tokens/cost/latency), not a stub - the same live pipeline, observed this time instead of
just graded on its findings.

Run: python scripts/phase10_observability_test.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scripts.phase8_agents_test import PLANTED_DIFF, REPO  # noqa: E402


async def main() -> int:
    from backend.observability.events import _pool_
    from backend.orchestrator.langgraph_engine import LangGraphEngine

    review_id = str(uuid.uuid4())
    engine = LangGraphEngine()
    initial = {
        "review_id": review_id,
        "repo": REPO,
        "pr_number": 999,
        "commit_sha": "phase10-observability",
        "diff": PLANTED_DIFF,
        "findings": [],
    }

    print(f"[review_id={review_id}] running full graph (real Groq + real retrieval)...")
    result = await engine.run(review_id, initial)
    print(f"decision={result.get('decision')} overall={result.get('overall_confidence')}\n")

    pool = await _pool_()
    rows = await pool.fetch(
        """
        SELECT ts, agent, span_id, parent_span, event_type, model, tokens_in, tokens_out,
               cost_usd, latency_ms, outcome, confidence, payload
        FROM agent_events WHERE review_id = $1 ORDER BY ts
        """,
        review_id,
    )

    print(f"{len(rows)} events reconstructed:")
    for r in rows:
        parent = str(r["parent_span"])[:8] if r["parent_span"] else "-"
        print(
            f"  {r['ts'].strftime('%H:%M:%S.%f')[:-3]}  {r['agent']:10} "
            f"span={str(r['span_id'])[:8]} parent={parent:8} {r['event_type']:10} "
            f"model={str(r['model'] or '-'):24} "
            f"tok={r['tokens_in']}/{r['tokens_out']} "
            f"cost=${r['cost_usd']} lat={r['latency_ms']}ms "
            f"outcome={r['outcome']} conf={r['confidence']}"
        )
    await pool.close()

    # --- DoD checks ---
    has_span_start = sum(1 for r in rows if r["event_type"] == "span.start") == 4
    has_span_end = sum(1 for r in rows if r["event_type"] == "span.end") == 4
    llm_calls = [r for r in rows if r["event_type"] == "llm.call"]
    has_llm_with_cost_latency = any(
        r["latency_ms"] is not None and r["tokens_in"] is not None for r in llm_calls
    )
    has_decision = sum(1 for r in rows if r["event_type"] == "decision") == 1
    # every non-top-level event's parent_span must point at a span_id that's actually
    # in this review's event set (real linking, not orphaned UUIDs)
    span_ids = {str(r["span_id"]) for r in rows}
    parents_ok = all(
        str(r["parent_span"]) in span_ids for r in rows if r["parent_span"] is not None
    )
    chronological = all(rows[i]["ts"] <= rows[i + 1]["ts"] for i in range(len(rows) - 1))

    print("\n[DoD] 4 span.start + 4 span.end (one pair per specialist)?", has_span_start and has_span_end)
    print("[DoD] at least one llm.call has real latency_ms + tokens_in?", has_llm_with_cost_latency)
    print("[DoD] exactly one decision event from the aggregator?", has_decision)
    print("[DoD] every child span's parent_span resolves within this review?", parents_ok)
    print("[DoD] events are chronologically ordered (ORDER BY ts)?", chronological)

    ok = all([has_span_start, has_span_end, has_llm_with_cost_latency, has_decision,
              parents_ok, chronological])
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
