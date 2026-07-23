"""ARQ worker + enqueue helpers.

The webhook handler enqueues a review job and returns immediately; the worker consumes it
asynchronously (ARCHITECTURE §3.1 - the queue decouples ingress from review). In Phase 3
the job is a stub that logs; Phase 4 replaces its body with a call into the orchestration
engine (core.workflow_engine.run)."""

from __future__ import annotations

import logging

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from backend.config import settings

logger = logging.getLogger("job_queue")

REVIEW_QUEUE = "arq:queue"


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings.redis_url)


async def get_arq_pool() -> ArqRedis:
    """Create a connection pool for enqueuing jobs (held on app.state in main.py)."""
    return await create_pool(redis_settings())


async def review_job(ctx: dict, review_id: str) -> str:
    """Phase 3 stub. Phase 4 swaps this for the LangGraph engine run."""
    logger.info("review_job received review_id=%s (stub - orchestration lands in Phase 4)", review_id)
    return review_id


class WorkerSettings:
    """Entrypoint for `arq backend.job_queue.arq_worker.WorkerSettings`."""

    functions = [review_job]
    redis_settings = redis_settings()
