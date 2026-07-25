"""FastAPI application entrypoint.

Wires the ingress webhook router and the read API, and manages two long-lived resources
over the app lifespan: the ARQ Redis pool (for enqueuing review jobs) and the async DB
engine (disposed on shutdown). Heavy review work runs in the ARQ worker, not here."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from backend.api import hitl_router
from backend.api import queue as queue_router
from backend.api import reviews as reviews_router
from backend.database.postgres import engine
from backend.job_queue.arq_worker import get_arq_pool
from backend.webhook_receiver import router as webhook_router

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.arq = await get_arq_pool()
    try:
        yield
    finally:
        await app.state.arq.aclose()
        await engine.dispose()


app = FastAPI(title="AI PR Review Agent", version="0.3.0", lifespan=lifespan)

app.include_router(webhook_router.router)
app.include_router(reviews_router.router)
app.include_router(queue_router.router)
app.include_router(hitl_router.router)


@app.get("/health")
async def health():
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ok", "db": "reachable"}
