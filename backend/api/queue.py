"""Read-only queue status endpoint for operational visibility."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/queue", tags=["queue"])


@router.get("/status")
async def queue_status(request: Request):
    pool = request.app.state.arq
    queued = await pool.queued_jobs()
    return {"queued": len(queued)}
