"""Human verdicts on a queued review (Phase 19).

approve_review: a human approves the queued review -> the findings are posted to the PR
(the "approving it from the API then posts the review" half of the DoD), the hitl_reviews
row is resolved 'approved'. reject_review: resolve 'rejected', mark the review rejected,
and post nothing. record_finding_feedback: capture a per-finding verdict
(confirmed/dismissed) into hitl_feedback for the learning loop (Phase 20)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import repository
from backend.integrations import review_poster
from backend.models.enums import HITLStatus


class HITLNotFound(Exception):
    """No open hitl_reviews row for the given review_id."""


async def approve_review(
    session: AsyncSession, review_id: uuid.UUID, reviewer: str
) -> str:
    """Post the review to GitHub, then resolve the queue entry as approved. Returns the
    GitHub review id. Posting happens BEFORE resolving, so if the post raises, the queue
    entry stays open (the human can retry) rather than being marked done with nothing
    posted."""
    hitl = await repository.get_open_hitl_review_for(session, review_id)
    if hitl is None:
        raise HITLNotFound(f"no open HITL review for {review_id}")
    github_review_id = await review_poster.post_review_for(session, review_id)
    await repository.resolve_hitl_review(
        session, hitl.id, HITLStatus.APPROVED.value, reviewer
    )
    return github_review_id


async def reject_review(
    session: AsyncSession, review_id: uuid.UUID, reviewer: str
) -> None:
    hitl = await repository.get_open_hitl_review_for(session, review_id)
    if hitl is None:
        raise HITLNotFound(f"no open HITL review for {review_id}")
    await repository.resolve_hitl_review(
        session, hitl.id, HITLStatus.REJECTED.value, reviewer
    )
    await repository.set_review_status(session, review_id, "rejected")


async def record_finding_feedback(
    session: AsyncSession, finding_id: uuid.UUID, verdict: str, comment: str | None = None
):
    return await repository.create_hitl_feedback(session, finding_id, verdict, comment)
