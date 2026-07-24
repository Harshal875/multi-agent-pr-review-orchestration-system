"""Embeds text via Voyage AI voyage-code-3 at 256 dims (matches code_chunks.embedding).

Shared by ingestion (Phase 14) and retrieval (Phase 6). Voyage distinguishes document
vs query embeddings via input_type: ingest chunks as "document", embed the PR diff/query
as "query". Batches by both text count and an estimated-token budget so a batch stays
under Voyage's per-request token cap; an optional inter-batch delay lets the ingestion
job respect the free tier's 3 requests/minute limit (the query path never throttles)."""

from __future__ import annotations

import time

import voyageai

from backend.config import settings

MODEL = "voyage-code-3"
DIMS = 256
_MAX_TEXTS_PER_BATCH = 128       # Voyage allows up to 1000; stay well under
_MAX_TOKENS_PER_BATCH = 8000     # under the free tier's 10K tokens/minute

_client: voyageai.Client | None = None


def _client_() -> voyageai.Client:
    global _client
    if _client is None:
        _client = voyageai.Client(api_key=settings.voyage_api_key)
    return _client


def _est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _batches(texts: list[str]):
    """Yield sublists bounded by both count and estimated-token budget."""
    i, n = 0, len(texts)
    while i < n:
        batch: list[str] = []
        toks = 0
        while (
            i < n
            and len(batch) < _MAX_TEXTS_PER_BATCH
            and (not batch or toks + _est_tokens(texts[i]) <= _MAX_TOKENS_PER_BATCH)
        ):
            batch.append(texts[i])
            toks += _est_tokens(texts[i])
            i += 1
        yield batch


def _embed(texts: list[str], input_type: str, delay_s: float = 0.0) -> list[list[float]]:
    out: list[list[float]] = []
    for idx, batch in enumerate(_batches(texts)):
        if idx > 0 and delay_s:
            time.sleep(delay_s)  # honor free-tier rate limit between requests
        result = _client_().embed(
            batch, model=MODEL, input_type=input_type, output_dimension=DIMS
        )
        out.extend(result.embeddings)
    return out


def embed_documents(texts: list[str], delay_s: float = 0.0) -> list[list[float]]:
    """Embed code chunks for storage (ingestion side). Pass delay_s to throttle."""
    return _embed(texts, "document", delay_s) if texts else []


def embed_query(text: str) -> list[float]:
    """Embed a single PR diff / query for retrieval (query side)."""
    return _embed([text], "query")[0]
