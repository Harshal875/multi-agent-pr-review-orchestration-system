"""Content-hash freshness tracking against repo_file_index, so ingestion only re-embeds
files that actually changed since the last run (ARCHITECTURE §3.5)."""

from __future__ import annotations

import hashlib


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def get_indexed_hash(cur, repo: str, path: str) -> str | None:
    cur.execute(
        "SELECT content_hash FROM repo_file_index WHERE repo=%s AND path=%s",
        (repo, path),
    )
    row = cur.fetchone()
    return row[0] if row else None


def record_indexed(cur, repo: str, path: str, hash_: str) -> None:
    cur.execute(
        """
        INSERT INTO repo_file_index (repo, path, content_hash, last_indexed_at)
        VALUES (%s, %s, %s, now())
        ON CONFLICT (repo, path)
        DO UPDATE SET content_hash = EXCLUDED.content_hash,
                      last_indexed_at = now()
        """,
        (repo, path, hash_),
    )
