"""Disputing an individual finding (Phase 19): a developer flags a specific finding as
wrong, writing a hitl_feedback row (verdict='disputed') linked by FK to the original
finding_records row. Distinct from feedback.reject_review (which is review-level and
gates posting) - a dispute can be filed against an ALREADY-POSTED finding, after the
fact, and feeds the learning loop rather than the posting gate."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import repository
from backend.database.models import HITLFeedback
from backend.models.enums import FeedbackVerdict


class FindingNotFound(Exception):
    """No finding_records row for the given finding_id."""


async def dispute_finding(
    session: AsyncSession, finding_id: uuid.UUID, comment: str | None = None
) -> HITLFeedback:
    finding = await repository.get_finding(session, finding_id)
    if finding is None:
        raise FindingNotFound(f"no finding {finding_id}")
    return await repository.create_hitl_feedback(
        session, finding_id, FeedbackVerdict.DISPUTED.value, comment
    )
