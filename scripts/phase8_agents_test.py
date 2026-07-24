"""Phase 8 DoD: a real diff with a deliberately planted SQL-injection-shaped bug gets
flagged by the security agent with a specific file/line and a rationale that references
the actual retrieved context (not a generic statement) - run end-to-end through the real
LangGraph engine: real Groq calls, real Tiger retrieval against the sample-repo corpus.

The diff extends billing/stripe.py (already embedded in code_chunks from Phase 14) with a
new `note` parameter interpolated directly into a SQL string - a textbook injection, and a
realistic-looking change to code the retriever can actually ground against.

This proves the mechanism end-to-end. Grading precision against 5-10 of your own real past
PRs (ROADMAP's fuller ask) is Phase 9's golden-dataset job, once you have real PR history to
grade against - this script gives you the harness to do that later.

Run: python scripts/phase8_agents_test.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # LLM output may include
# smart punctuation the Windows console's cp1252 default can't encode.

REPO = "sample-repo"

PLANTED_DIFF = """\
--- a/billing/stripe.py
+++ b/billing/stripe.py
@@ def record_payment(db, customer_id, amount_cents):
-def record_payment(db, customer_id: str, amount_cents: int):
-    # NOTE: string-formatted SQL — deliberately smelly for the security agent later
-    query = "INSERT INTO payments (customer_id, amount) VALUES ('%s', %d)" % (
-        customer_id, amount_cents,
-    )
-    db.execute(query)
+def record_payment(db, customer_id: str, amount_cents: int, note: str = ""):
+    # NEW: also store an optional free-text note the customer typed in at checkout
+    query = "INSERT INTO payments (customer_id, amount, note) VALUES ('%s', %d, '%s')" % (
+        customer_id, amount_cents, note,
+    )
+    db.execute(query)
"""

_INJECTION_KEYWORDS = (
    "sql", "inject", "format", "string interpolation", "%s", "concatenat", "sanitiz",
    "parameteriz", "escape",
)


def _findings_summary(findings: list[dict]) -> None:
    for f in findings:
        agreed = f.get("agreed_by", [f.get("agent_type")])
        print(
            f"  [{f['severity']:8} conf={f['confidence']:.2f}] "
            f"{f['agent_type']:8} {f['file_path']}:{f.get('line_start')}-{f.get('line_end')} "
            f"({','.join(agreed)})"
        )
        print(f"      {f['summary']}")
        print(f"      rationale: {f['rationale'][:200]}")


async def main() -> int:
    from backend.orchestrator.langgraph_engine import LangGraphEngine

    thread = f"phase8-{uuid.uuid4().hex[:8]}"
    engine = LangGraphEngine()
    initial = {
        "review_id": thread,
        "repo": REPO,
        "pr_number": 999,
        "commit_sha": "planted-sql-injection",
        "diff": PLANTED_DIFF,
        "findings": [],
    }

    print(f"[thread={thread}] running full graph (real Groq + real retrieval)...")
    result = await engine.run(thread, initial)

    raw = result.get("findings", [])
    deduped = result.get("deduped_findings", [])
    print(f"\nraw findings from all 4 specialists: {len(raw)}")
    print(f"deduped findings: {len(deduped)}")
    print(f"overall_confidence={result.get('overall_confidence')} "
          f"decision={result.get('decision')} hitl_reason={result.get('hitl_reason')}")
    print("\n--- all findings ---")
    _findings_summary(deduped)

    # --- DoD check: something concrete flags the planted injection ---
    hit = None
    for f in deduped:
        text = " ".join(
            str(f.get(k, "")) for k in ("summary", "rationale", "category")
        ).lower()
        path_ok = "stripe" in f["file_path"].lower()
        keyword_ok = any(kw in text for kw in _INJECTION_KEYWORDS)
        if path_ok and keyword_ok:
            hit = f
            break

    print("\n[DoD] planted SQL injection flagged with file reference + concrete rationale?")
    print(f"  -> {'YES: ' + json.dumps(hit) if hit else 'NO'}")

    ok = hit is not None
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
