"""Read endpoints for reviews and their findings. Used by the frontend (Phase 2/17) and
for manual verification now."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.schemas import FindingOut, ReviewOut
from backend.database.postgres import get_session
from backend.database.repository import get_findings, get_review, list_reviews
from backend.observability.audit import get_review_audit

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.get("", response_model=list[ReviewOut])
async def list_all(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    return list(await list_reviews(session, limit=limit, offset=offset))


@router.get("/{review_id}", response_model=ReviewOut)
async def get_one(review_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    record = await get_review(session, review_id)
    if record is None:
        raise HTTPException(status_code=404, detail="review not found")
    return record


@router.get("/{review_id}/findings", response_model=list[FindingOut])
async def get_review_findings(
    review_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    if await get_review(session, review_id) is None:
        raise HTTPException(status_code=404, detail="review not found")
    return list(await get_findings(session, review_id))


@router.get("/{review_id}/audit")
async def get_review_audit_endpoint(
    review_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """Phase 15: for every finding in this review, the full decision trail (what was
    retrieved, what prompt/model ran, what confidence resulted) - "why did the agent
    say this?" answerable from this response alone."""
    if await get_review(session, review_id) is None:
        raise HTTPException(status_code=404, detail="review not found")
    return await get_review_audit(review_id)
