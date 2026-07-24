"""Hybrid retrieval: run the vector and keyword lanes and fuse them with Reciprocal Rank
Fusion (ARCHITECTURE §3.5). Vector search catches meaning; keyword search catches exact
identifiers (function names, error codes); RRF merges both rankings without needing the
two score scales to be comparable. Returns the top-k fused chunks for a specialist prompt.

retrieve() is retry-wrapped (Phase 12): live testing (Phase 8) showed Voyage's free-tier
rate limit (3 RPM) tripping under 4-way concurrent specialist load - a short backoff-
and-retry clears most of these without the caller ever seeing a failure, rather than
base_agent.py falling straight back to "continue ungrounded" on the first hiccup."""

from __future__ import annotations

import asyncio
from typing import Any

import voyageai.error as voyage_error

from backend.memory.embedder import embed_query
from backend.memory.redis_client import get_cached, set_cached
from backend.memory.tiger_client import get_memory_client
from backend.reliability.retry import with_retry

_RETRYABLE = (
    voyage_error.RateLimitError,
    voyage_error.APIConnectionError,
    voyage_error.ServerError,
    voyage_error.ServiceUnavailableError,
    voyage_error.Timeout,
    voyage_error.TryAgain,
)

_RRF_K = 60  # standard RRF constant; dampens the weight of lower ranks


def _rrf_merge(
    lanes: list[list[dict[str, Any]]], k: int
) -> list[dict[str, Any]]:
    scores: dict[Any, float] = {}
    items: dict[Any, dict[str, Any]] = {}
    for lane in lanes:
        for rank, row in enumerate(lane, start=1):
            cid = row["id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank)
            items.setdefault(cid, row)
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    out: list[dict[str, Any]] = []
    for cid, score in ordered[:k]:
        row = items[cid]
        out.append(
            {
                "id": str(cid),
                "path": row["path"],
                "symbol": row["symbol"],
                "content": row["content"],
                "score": round(score, 6),
            }
        )
    return out


@with_retry(max_attempts=3, base_delay_s=1.0, max_delay_s=15.0, retry_on=_RETRYABLE)
async def retrieve(
    repo: str, diff_text: str, k: int = 5, per_lane: int = 10, use_cache: bool = True
) -> list[dict[str, Any]]:
    """Return the top-k codebase chunks relevant to a PR diff, fused across both lanes."""
    if use_cache:
        cached = await get_cached(repo, diff_text)
        if cached is not None:
            return cached

    client = get_memory_client()
    # embed_query is a blocking network call; keep the event loop free.
    embedding = await asyncio.to_thread(embed_query, diff_text)

    vector_hits, keyword_hits = await asyncio.gather(
        client.vector_search(repo, embedding, per_lane),
        client.keyword_search(repo, diff_text, per_lane),
    )
    merged = _rrf_merge([vector_hits, keyword_hits], k)

    if use_cache:
        await set_cached(repo, diff_text, merged)
    return merged
