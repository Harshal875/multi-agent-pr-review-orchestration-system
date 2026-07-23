"""POST /webhooks/github - the ingress endpoint.

Does exactly three things and returns fast (ARCHITECTURE §3.1):
  1. verify the HMAC-SHA256 signature (reject forgeries),
  2. check the delivery_id for idempotency (insert a pending row; a replay is a no-op),
  3. enqueue a review job and return 200 immediately.
Heavy work happens later in the ARQ worker."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database.postgres import get_session
from backend.database.repository import create_pending_review
from backend.webhook_receiver.parser import parse_pull_request_event
from backend.webhook_receiver.validator import verify_signature

logger = logging.getLogger("webhook")
router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/github")
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
):
    body = await request.body()

    # 1. Authenticity - reject forgeries before doing anything else.
    if not verify_signature(settings.github_webhook_secret, body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="invalid signature")

    if x_github_event == "ping":
        return {"ok": True, "pong": True}
    if x_github_event != "pull_request":
        return {"ignored_event": x_github_event}
    if not x_github_delivery:
        raise HTTPException(status_code=400, detail="missing X-GitHub-Delivery")

    payload = json.loads(body)
    event = parse_pull_request_event(payload, x_github_delivery)
    if event is None:
        return {"ignored_action": payload.get("action")}

    # 2. Idempotency - a replayed delivery returns the existing row, no duplicate.
    record, created = await create_pending_review(session, event)

    # 3. Enqueue only on first sight; ack fast.
    if created:
        await request.app.state.arq.enqueue_job("review_job", str(record.id))
        logger.info("enqueued review_id=%s repo=%s pr=%s", record.id, event.repo, event.pr_number)
    else:
        logger.info("duplicate delivery=%s -> review_id=%s (no re-enqueue)", event.delivery_id, record.id)

    return JSONResponse(
        status_code=200,
        content={
            "review_id": str(record.id),
            "status": record.status,
            "duplicate": not created,
        },
    )
