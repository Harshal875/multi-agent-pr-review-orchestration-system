"""ARQ worker + enqueue helpers.

The webhook handler enqueues a review job and returns immediately; the worker consumes it
and drives the orchestration engine (ARCHITECTURE §3.1 - the queue decouples ingress from
review). As of Phase 4 review_job loads the pending review row, builds the initial
ReviewState, and calls the workflow engine (LangGraph fan-out). The engine checkpoints to
Redis, so if this worker is killed mid-review the job re-runs and resumes from the last
completed node.

Phase 15 added the missing write-back: once the engine returns, repository.complete_review
persists the aggregator's deduped findings + overall_confidence to the truth lane
(finding_records / pr_review_records) - before this, agent output only ever lived in the
LangGraph checkpoint, and GET /reviews/{id}/findings had always returned an empty list for
every real review."""

from __future__ import annotations

import logging
import uuid

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from backend.config import settings

logger = logging.getLogger("job_queue")


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings.redis_url)


async def get_arq_pool() -> ArqRedis:
    """Connection pool for enqueuing jobs (held on app.state in main.py)."""
    return await create_pool(redis_settings())


async def review_job(ctx: dict, review_id: str) -> str | None:
    """Run one PR review through the orchestration engine."""
    from backend.database import repository
    from backend.database.postgres import SessionLocal
    from backend.orchestrator.langgraph_engine import get_engine

    async with SessionLocal() as session:
        record = await repository.get_review(session, uuid.UUID(review_id))

    if record is None:
        logger.error("review_job: no review row for review_id=%s", review_id)
        return None

    initial_state = {
        "review_id": review_id,
        "repo": record.repo,
        "pr_number": record.pr_number,
        "commit_sha": record.commit_sha,
        "diff": "",          # Phase 8+: fetch real diff via integrations/github_client
        "findings": [],
    }

    engine = get_engine()
    result = await engine.run(review_id, initial_state)
    decision = result.get("decision")

    async with SessionLocal() as session:
        await repository.complete_review(
            session, uuid.UUID(review_id),
            decision=decision,
            overall_confidence=result.get("overall_confidence"),
            findings=result.get("deduped_findings", []),
        )

    logger.info("review_job done review_id=%s decision=%s", review_id, decision)
    return decision


class WorkerSettings:
    """Entrypoint for `arq backend.job_queue.arq_worker.WorkerSettings`."""

    functions = [review_job]
    redis_settings = redis_settings()
