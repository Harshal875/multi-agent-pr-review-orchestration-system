"""REST surface for the human-in-the-loop queue (Phase 19). This is where Phase 11's RBAC
finally gates real routes (it was built unwired then, by design): listing the queue needs
VIEWER; approving/rejecting/disputing needs APPROVER - actions that change what gets
posted to a real PR.

Auth is header-based (X-User-Role) via auth/dependencies.require_role - a placeholder for
a real session/identity system, honest about being one (see auth/dependencies.py)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.dependencies import require_role
from backend.database.postgres import get_session
from backend.hitl import dispute, feedback, queue
from backend.security.rbac import Role

router = APIRouter(prefix="/hitl", tags=["hitl"])


class ApproveIn(BaseModel):
    reviewer: str


class DisputeIn(BaseModel):
    comment: str | None = None


@router.get("/reviews", dependencies=[Depends(require_role(Role.VIEWER))])
async def list_open_reviews(session: AsyncSession = Depends(get_session)):
    rows = await queue.list_open(session)
    return [
        {
            "hitl_id": str(r.id),
            "review_id": str(r.review_id),
            "reason": r.reason,
            "status": r.status,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/reviews/{review_id}/approve", dependencies=[Depends(require_role(Role.APPROVER))])
async def approve(
    review_id: uuid.UUID, body: ApproveIn, session: AsyncSession = Depends(get_session)
):
    try:
        github_review_id = await feedback.approve_review(session, review_id, body.reviewer)
    except feedback.HITLNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "posted", "github_review_id": github_review_id}


@router.post("/reviews/{review_id}/reject", dependencies=[Depends(require_role(Role.APPROVER))])
async def reject(
    review_id: uuid.UUID, body: ApproveIn, session: AsyncSession = Depends(get_session)
):
    try:
        await feedback.reject_review(session, review_id, body.reviewer)
    except feedback.HITLNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "rejected"}


@router.post("/findings/{finding_id}/dispute", dependencies=[Depends(require_role(Role.APPROVER))])
async def dispute_finding(
    finding_id: uuid.UUID, body: DisputeIn, session: AsyncSession = Depends(get_session)
):
    try:
        row = await dispute.dispute_finding(session, finding_id, body.comment)
    except dispute.FindingNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"feedback_id": str(row.id), "finding_id": str(finding_id), "verdict": row.verdict}
