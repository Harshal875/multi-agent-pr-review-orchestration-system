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
