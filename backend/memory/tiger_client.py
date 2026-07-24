"""TigerMemoryClient — the two retrieval lanes over code_chunks (ARCHITECTURE §3.5).

Vector lane: DiskANN ANN search on the 256-dim embedding (cosine distance).
Keyword lane: full-text search over the generated content_tsv GIN index.

Uses asyncpg directly (the hot request-path access style, per ADR-003) with a lazily
created pool. Replaces the retired qdrant_client (ADR-003)."""

from __future__ import annotations

from typing import Any

import asyncpg

from backend.config import settings
from backend.database.asyncpg_dsn import dsn_and_ssl


def _vec_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"


class TigerMemoryClient:
    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None

    async def _pool_(self) -> asyncpg.Pool:
        if self._pool is None:
            dsn, ctx = dsn_and_ssl(settings.tiger_database_url)
            self._pool = await asyncpg.create_pool(dsn=dsn, ssl=ctx, min_size=1, max_size=5)
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def vector_search(
        self, repo: str, embedding: list[float], k: int = 10
    ) -> list[dict[str, Any]]:
        """DiskANN ANN search — nearest chunks by cosine distance (lower = closer)."""
        vec = _vec_literal(embedding)
        pool = await self._pool_()
        rows = await pool.fetch(
            """
            SELECT id, path, symbol, content,
                   (embedding <=> $2::vector) AS distance
            FROM code_chunks
            WHERE repo = $1
            ORDER BY embedding <=> $2::vector
            LIMIT $3
            """,
            repo, vec, k,
        )
        return [dict(r) for r in rows]

    async def keyword_search(
        self, repo: str, query_text: str, k: int = 10
    ) -> list[dict[str, Any]]:
        """Full-text GIN search.

        A PR diff is many words; plainto_/websearch_to_tsquery AND them together, so a
        long diff matches nothing (an over-restrictive query defeats the keyword lane).
        Instead we reduce the query text to its own lexemes (via to_tsvector, the same
        normalization that built content_tsv) and OR them — so any shared identifier or
        term produces a match. Deriving the tsquery from unnest(to_tsvector(...)) is also
        injection-safe: no user text reaches to_tsquery unlexemized."""
        pool = await self._pool_()
        rows = await pool.fetch(
            """
            SELECT id, path, symbol, content,
                   ts_rank_cd(content_tsv, q) AS rank
            FROM code_chunks,
                 to_tsquery('english',
                     (SELECT string_agg(lexeme, ' | ')
                      FROM unnest(to_tsvector('english', $2)))
                 ) AS q
            WHERE repo = $1 AND content_tsv @@ q
            ORDER BY rank DESC
            LIMIT $3
            """,
            repo, query_text, k,
        )
        return [dict(r) for r in rows]


_client: TigerMemoryClient | None = None


def get_memory_client() -> TigerMemoryClient:
    global _client
    if _client is None:
        _client = TigerMemoryClient()
    return _client
