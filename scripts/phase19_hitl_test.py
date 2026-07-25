"""Phase 19 DoD: a deliberately low-confidence/CRITICAL run stops at the queue instead of
posting to GitHub; approving it from the API then posts the review; the hitl_feedback row
for a disputed finding is queryable and linked back to the original finding_records row.

Runs end-to-end against the real repo Harshal875/pravak-ai PR #11 (has a planted eval()
RCE + string-formatted SQL). The eval() -> CRITICAL -> escalation -> the review stops at
the HITL queue, unposted. We then approve via the real API (ASGI), which posts a real
review to the PR, and dispute a finding, checking the hitl_feedback FK link.

The exact review body is printed BEFORE the approve step posts it, so the first real
GitHub post is visible, not silent.

Run: python scripts/phase19_hitl_test.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = "Harshal875/pravak-ai"
PR_NUMBER = 11


async def main() -> int:
    import httpx
    from httpx import ASGITransport

    from backend.database import repository
    from backend.database.models import PRReviewRecord
    from backend.database.postgres import SessionLocal
    from backend.integrations.review_poster import format_review_body
    from backend.job_queue.arq_worker import review_job
    from backend.main import app

    review_id = uuid.uuid4()

    # --- seed a pending review row for the real PR, as the webhook handler would ---
    async with SessionLocal() as session:
        session.add(PRReviewRecord(
            id=review_id, repo=REPO, pr_number=PR_NUMBER, commit_sha="phase19-test",
            delivery_id=f"phase19-{review_id}",
        ))
        await session.commit()

    print(f"[review_id={review_id}] running review_job against {REPO} PR #{PR_NUMBER} "
          f"(real diff fetch + agents + routing)...")
    decision = await review_job({}, str(review_id))
    print(f"decision={decision}")

    # --- DoD part 1: stopped at the queue, NOT posted ---
    async with SessionLocal() as session:
        review = await repository.get_review(session, review_id)
        hitl = await repository.get_open_hitl_review_for(session, review_id)
        findings = list(await repository.get_findings(session, review_id))

    queued = hitl is not None
    not_posted = review.status != "posted" and review.github_review_id is None
    print(f"\n[DoD-1] review stopped at HITL queue (open row exists)? {queued} "
          f"(reason={hitl.reason if hitl else None})")
    print(f"[DoD-1] NOT posted to GitHub yet (status={review.status}, "
          f"github_review_id={review.github_review_id})? {not_posted}")
    print(f"        findings persisted: {len(findings)}")

    # --- show exactly what will be posted, before posting it ---
    print("\n--- review body that the approve step will post to the PR ---")
    print(format_review_body(review, findings)[:1200])
    print("--- (truncated) ---")

    # --- DoD part 2: approve via the real API -> posts the review ---
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # RBAC: approver role required
        r_noauth = await c.post(f"/hitl/reviews/{review_id}/approve",
                                json={"reviewer": "harshal"})
        r_approve = await c.post(f"/hitl/reviews/{review_id}/approve",
                                 json={"reviewer": "harshal"},
                                 headers={"X-User-Role": "approver"})
    print(f"\n[DoD-2] approve without approver role rejected? "
          f"{r_noauth.status_code == 401} ({r_noauth.status_code})")
    print(f"[DoD-2] approve (approver) -> {r_approve.status_code} {r_approve.json()}")

    async with SessionLocal() as session:
        review2 = await repository.get_review(session, review_id)
        hitl2 = await repository.get_open_hitl_review_for(session, review_id)
    posted = review2.status == "posted" and review2.github_review_id is not None
    queue_resolved = hitl2 is None  # no longer 'open'
    print(f"[DoD-2] now posted (status={review2.status}, "
          f"github_review_id={review2.github_review_id})? {posted}")
    print(f"[DoD-2] HITL queue entry resolved (no longer open)? {queue_resolved}")
    if posted:
        print(f"        -> live review: https://github.com/{REPO}/pull/{PR_NUMBER}#pullrequestreview-{review2.github_review_id}")

    # --- DoD part 3: dispute a finding -> hitl_feedback row linked to finding_records ---
    target = findings[0]
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r_dispute = await c.post(
            f"/hitl/findings/{target.id}/dispute",
            json={"comment": "disagree - this is a false positive in my view"},
            headers={"X-User-Role": "approver"},
        )
    print(f"\n[DoD-3] dispute finding {target.id} -> {r_dispute.status_code} {r_dispute.json()}")

    async with SessionLocal() as session:
        feedback_rows = list(await repository.get_feedback_for_finding(session, target.id))
    linked = (
        len(feedback_rows) == 1
        and feedback_rows[0].finding_id == target.id
        and feedback_rows[0].verdict == "disputed"
    )
    print(f"[DoD-3] hitl_feedback row queryable + linked to finding_records "
          f"(FK finding_id matches)? {linked}")

    ok = (queued and not_posted and r_noauth.status_code == 401
          and r_approve.status_code == 200 and posted and queue_resolved and linked)
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
