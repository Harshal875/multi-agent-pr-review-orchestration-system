"""hitl_reviews lifecycle (Phase 19): a review the gate/escalation routed to a human
lands here as an 'open' row, and this is what the dashboard/API lists. Thin orchestration
over repository.py (which owns the actual ORM), per ADR-002."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import repository
from backend.database.models import HITLReview


async def enqueue(session: AsyncSession, review_id: uuid.UUID, reason: str) -> HITLReview:
    """Insert an open hitl_reviews row. Also flips the review's own status to
    awaiting_human so the truth lane and the queue agree."""
    await repository.set_review_status(session, review_id, "awaiting_human")
    return await repository.create_hitl_review(session, review_id, reason)


async def list_open(session: AsyncSession):
    return await repository.list_open_hitl_reviews(session)
