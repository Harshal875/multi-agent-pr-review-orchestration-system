"""Repository over the truth-lane tables - the single place ORM queries for reviews and
findings live, so callers depend on a narrow interface (ADR-002)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import FindingRecord, PRReviewRecord
from backend.models.webhook import WebhookEvent
from backend.reliability.idempotency import idempotent_insert


async def create_pending_review(
    session: AsyncSession, event: WebhookEvent
) -> tuple[PRReviewRecord, bool]:
    """Insert a 'pending' review keyed by delivery_id (the idempotency key).

    Returns (record, created). If a row with this delivery_id already exists (a replayed
    GitHub delivery), no new row is written and the existing record is returned with
    created=False. This is the L8 idempotency defense at the data layer, formalized as
    reliability/idempotency.py's idempotent_insert() (Phase 12) rather than the hand-
    rolled insert/conflict/fetch dance this function used before.
    """
    stmt = (
        pg_insert(PRReviewRecord)
        .values(
            repo=event.repo,
            pr_number=event.pr_number,
            commit_sha=event.commit_sha,
            delivery_id=event.delivery_id,
        )
        .on_conflict_do_nothing(index_elements=["delivery_id"])
        .returning(PRReviewRecord)
    )
    return await idempotent_insert(
        session,
        stmt,
        lambda: session.scalar(
            select(PRReviewRecord).where(PRReviewRecord.delivery_id == event.delivery_id)
        ),
    )


async def get_review(session: AsyncSession, review_id: uuid.UUID) -> PRReviewRecord | None:
    return await session.get(PRReviewRecord, review_id)


async def list_reviews(
    session: AsyncSession, limit: int = 50, offset: int = 0
) -> Sequence[PRReviewRecord]:
    result = await session.execute(
        select(PRReviewRecord)
        .order_by(PRReviewRecord.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()


async def get_findings(
    session: AsyncSession, review_id: uuid.UUID
) -> Sequence[FindingRecord]:
    result = await session.execute(
        select(FindingRecord)
        .where(FindingRecord.review_id == review_id)
        .order_by(FindingRecord.created_at.asc())
    )
    return result.scalars().all()


async def complete_review(
    session: AsyncSession,
    review_id: uuid.UUID,
    *,
    decision: str | None,
    overall_confidence: float | None,
    findings: list[dict],
) -> None:
    """Persist the aggregator's output (Phase 8) to the truth lane: one FindingRecord per
    deduped finding, and the review's overall_confidence - this is the gap Phase 15's
    audit endpoint needs closed, since nothing wrote agent output to finding_records
    before this (GET /reviews/{id}/findings had always returned an empty list for every
    real review).

    A "post" decision does NOT set status='posted' here - no GitHub-posting capability
    exists yet (integrations/github_client.py is still a Phase-1 stub), so claiming
    'posted' would misrepresent state that hasn't actually happened. status only
    advances to 'awaiting_human', which is unconditionally true the moment the gate
    routes there. Whichever phase wires real GitHub delivery should set status='posted'
    and posted_at at the point delivery actually succeeds, not here."""
    review = await session.get(PRReviewRecord, review_id)
    if review is None:
        return

    review.overall_confidence = overall_confidence
    if decision == "awaiting_human":
        review.status = "awaiting_human"

    for f in findings:
        session.add(
            FindingRecord(
                review_id=review_id,
                agent_type=f["agent_type"],
                severity=f["severity"],
                category=f["category"],
                summary=f["summary"],
                file_path=f["file_path"],
                line_start=f.get("line_start"),
                line_end=f.get("line_end"),
                suggestion=f.get("suggestion"),
                confidence=f["confidence"],
                rationale=f["rationale"],
            )
        )
    await session.commit()
