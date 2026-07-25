"""Phase 15 DoD: for any finding ID, you can answer "why did the agent say this?" from
the API response alone, no code-reading required.

This also closes a real prerequisite gap this phase's own testing found: nothing ever
wrote agent output to finding_records before this - GET /reviews/{id}/findings had
always returned an empty list for every real review, since the aggregator's output only
ever lived in the LangGraph checkpoint. repository.complete_review() (wired into
job_queue/arq_worker.py) closes that; this test exercises the same path directly rather
than going through the full webhook+ARQ machinery.

Run: python scripts/phase15_audit_test.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scripts.phase11_security_test import ATTACK_DIFF, FAKE_SECRET  # noqa: E402
from scripts.phase8_agents_test import REPO  # noqa: E402


async def main() -> int:
    from backend.database.models import PRReviewRecord
    from backend.database.postgres import SessionLocal
    from backend.database.repository import complete_review, get_findings
    from backend.observability.audit import get_review_audit
    from backend.orchestrator.langgraph_engine import LangGraphEngine

    review_id = uuid.uuid4()

    # --- set up a real pr_review_records row, as the webhook handler would ---
    async with SessionLocal() as session:
        session.add(PRReviewRecord(
            id=review_id, repo=REPO, pr_number=994, commit_sha="phase15-audit-test",
            delivery_id=f"phase15-{review_id}",
        ))
        await session.commit()

    # --- run the real pipeline against Phase 11's attack diff (injection + secret + RCE) ---
    engine = LangGraphEngine()
    initial = {
        "review_id": str(review_id), "repo": REPO, "pr_number": 994,
        "commit_sha": "phase15-audit-test", "diff": ATTACK_DIFF, "findings": [],
    }
    print(f"[review_id={review_id}] running full graph...")
    result = await engine.run(str(review_id), initial)
    print(f"decision={result.get('decision')} "
          f"deduped_findings={len(result.get('deduped_findings', []))}")

    # --- persist (the gap this phase closes) ---
    async with SessionLocal() as session:
        await complete_review(
            session, review_id,
            decision=result.get("decision"),
            overall_confidence=result.get("overall_confidence"),
            findings=result.get("deduped_findings", []),
        )

    # --- DoD check 1: finding_records is no longer empty for a real review ---
    async with SessionLocal() as session:
        persisted = await get_findings(session, review_id)
    print(f"\npersisted finding_records rows: {len(persisted)}")
    for f in persisted:
        print(f"  [{f.severity:8}] {f.summary}  (id={f.id})")
    findings_persisted = len(persisted) > 0

    # --- DoD check 2: the audit endpoint answers "why" for a real finding, no code needed ---
    import httpx
    from httpx import ASGITransport

    from backend.main import app

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/reviews/{review_id}/audit")
    print(f"\nGET /reviews/{review_id}/audit -> {resp.status_code}")
    audit = resp.json()
    print(f"audit entries returned: {len(audit)}")

    ok = findings_persisted and resp.status_code == 200 and len(audit) == len(persisted)

    # Pick the security finding about the eval() RCE and show its full trail is
    # self-explanatory: retrieval (what was grounded), llm.call (what model/tokens/cost),
    # and the finding's own confidence/rationale - "why did the agent say this?"
    rce_entry = next(
        (a for a in audit if a["agent_type"] == "security"
         and "eval" in (a["summary"] + a["rationale"]).lower()),
        None,
    )
    if rce_entry:
        print(f"\n--- audit trail for finding {rce_entry['finding_id']} ---")
        print(f"  severity={rce_entry['severity']} confidence={rce_entry['confidence']}")
        print(f"  summary: {rce_entry['summary']}")
        print(f"  rationale: {rce_entry['rationale'][:150]}")
        print(f"  trail ({len(rce_entry['trail'])} events):")
        event_types_seen = set()
        for ev in rce_entry["trail"]:
            event_types_seen.add(ev["event_type"])
            extra = ""
            if ev["event_type"] == "retrieval" and ev["payload"]:
                extra = f" chunks={[c['path'] for c in ev['payload'].get('chunks', [])]}"
            elif ev["event_type"] == "llm.call":
                extra = f" model={ev['model']} tokens={ev['tokens_in']}/{ev['tokens_out']} cost=${ev['cost_usd']}"
            print(f"    {ev['ts']}  {ev['event_type']:10} outcome={ev['outcome']}{extra}")

        has_retrieval = "retrieval" in event_types_seen
        has_llm_call = "llm.call" in event_types_seen
        has_tool_call = "tool.call" in event_types_seen
        secret_leaked_in_audit = FAKE_SECRET in str(rce_entry)

        print(f"\n[DoD] trail shows what was retrieved? {has_retrieval}")
        print(f"[DoD] trail shows what model ran (llm.call)? {has_llm_call}")
        print(f"[DoD] trail shows the static-analysis tool call? {has_tool_call}")
        print(f"[DoD] the raw secret is NOT leaked into the audit response? {not secret_leaked_in_audit}")

        ok = ok and has_retrieval and has_llm_call and has_tool_call and not secret_leaked_in_audit
    else:
        print("\n[DoD] could not find the RCE finding in the audit response")
        ok = False

    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
