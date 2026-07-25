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
    """Run one PR review through the orchestration engine, persist findings, then either
    auto-post to GitHub (high-confidence, no CRITICAL) or route to the HITL queue
    (Phase 19)."""
    from backend.database import repository
    from backend.database.postgres import SessionLocal
    from backend.hitl import escalation, queue
    from backend.integrations.github_client import get_github_client
    from backend.integrations.review_poster import post_review_for
    from backend.orchestrator.langgraph_engine import get_engine

    rid = uuid.UUID(review_id)
    async with SessionLocal() as session:
        record = await repository.get_review(session, rid)

    if record is None:
        logger.error("review_job: no review row for review_id=%s", review_id)
        return None

    # Fetch the real PR diff (Phase 19). If GitHub is unreachable, degrade to an empty
    # diff and let the review run ungrounded rather than failing the job outright.
    try:
        diff = await get_github_client().fetch_pr_diff(record.repo, record.pr_number)
    except Exception as exc:  # noqa: BLE001
        logger.warning("review_job: diff fetch failed for %s#%s: %s",
                       record.repo, record.pr_number, exc)
        diff = ""

    initial_state = {
        "review_id": review_id,
        "repo": record.repo,
        "pr_number": record.pr_number,
        "commit_sha": record.commit_sha,
        "diff": diff,
        "findings": [],
    }

    engine = get_engine()
    result = await engine.run(review_id, initial_state)
    decision = result.get("decision")
    deduped = result.get("deduped_findings", [])

    async with SessionLocal() as session:
        await repository.complete_review(
            session, rid, decision=decision,
            overall_confidence=result.get("overall_confidence"), findings=deduped,
        )

    # Route: CRITICAL or low-confidence -> HITL queue; otherwise auto-post.
    route_to_human, reason = escalation.should_route_to_human(decision, deduped)
    async with SessionLocal() as session:
        if route_to_human:
            await queue.enqueue(session, rid, reason)
            logger.info("review_job review_id=%s -> HITL queue (reason=%s)", review_id, reason)
        else:
            try:
                gh_id = await post_review_for(session, rid)
                logger.info("review_job review_id=%s -> auto-posted (github_review_id=%s)",
                            review_id, gh_id)
            except Exception as exc:  # noqa: BLE001 - a failed post shouldn't crash the job
                logger.warning("review_job: auto-post failed for %s: %s", review_id, exc)

    return decision


class WorkerSettings:
    """Entrypoint for `arq backend.job_queue.arq_worker.WorkerSettings`."""

    functions = [review_job]
    redis_settings = redis_settings()
