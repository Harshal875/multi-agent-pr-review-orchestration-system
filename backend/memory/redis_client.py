"""Session-level retrieval cache (ARCHITECTURE §3.5): identical diffs shouldn't re-embed
or re-query. Keyed by (repo, sha256(diff)). Best-effort — every cache op is wrapped so a
Redis outage degrades to a live retrieval rather than an error. Distinct from the ARQ
queue's Redis usage."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import redis.asyncio as aioredis

from backend.config import settings

logger = logging.getLogger("memory.cache")

_CACHE_TTL = 3600  # 1 hour
_client: aioredis.Redis | None = None


def _client_() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _client


def _key(repo: str, diff_text: str) -> str:
    digest = hashlib.sha256(diff_text.encode("utf-8", errors="replace")).hexdigest()
    return f"retrieval:{repo}:{digest}"


async def get_cached(repo: str, diff_text: str) -> list[dict[str, Any]] | None:
    try:
        raw = await _client_().get(_key(repo, diff_text))
        return json.loads(raw) if raw else None
    except Exception as exc:  # noqa: BLE001 - cache is best-effort
        logger.warning("retrieval cache get failed: %s", exc)
        return None


async def set_cached(repo: str, diff_text: str, results: list[dict[str, Any]]) -> None:
    try:
        await _client_().set(
            _key(repo, diff_text), json.dumps(results, default=str), ex=_CACHE_TTL
        )
    except Exception as exc:  # noqa: BLE001 - cache is best-effort
        logger.warning("retrieval cache set failed: %s", exc)
