"""Code-chunk ingestion pipeline (Phase 14).

Walks a repository, chunks each text/code file, embeds the chunks (Voyage voyage-code-3),
and upserts them into code_chunks. Uses the freshness tracker so a second run over an
unchanged repo re-embeds nothing. Runs as a batch/CLI job over psycopg (sync) — the hot
request-path writes use asyncpg later; ingestion is offline, so a simple sync path is fine.

Embedding is deferred to one throttled, batched sweep (not one call per file) so ingestion
respects Voyage's free-tier limit of 3 requests/minute.

Usage:
    python -m backend.data.ingestion <repo_path> [repo_name]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import psycopg

from backend.config import settings
from backend.data.freshness import content_hash, get_indexed_hash, record_indexed
from backend.memory.embedder import embed_documents
from backend.security.masking import mask_secrets

# Which files to index — source/text; everything else (binaries, media) is skipped.
TEXT_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".rb", ".php",
    ".c", ".h", ".cpp", ".hpp", ".cs", ".kt", ".swift", ".scala", ".sh",
    ".sql", ".md", ".rst", ".txt", ".toml", ".yaml", ".yml", ".json", ".cfg", ".ini",
}
IGNORE_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist",
    "build", ".mypy_cache", ".pytest_cache", ".ruff_cache", "target", ".idea", ".vscode",
}
MAX_FILE_BYTES = 500_000       # skip very large files
CHUNK_LINES = 50               # fixed-line-count chunking (per ROADMAP §Phase 14)
CHUNK_OVERLAP = 10

_SYMBOL_RE = re.compile(
    r"^\s*(?:def|class|func|function|type|interface|struct)\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.MULTILINE,
)


def iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in IGNORE_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield path


def chunk_text(content: str) -> list[tuple[int, str, str | None]]:
    """Fixed-line-count chunks with overlap. Returns (chunk_index, text, symbol|None)."""
    lines = content.splitlines()
    if not lines:
        return []
    chunks: list[tuple[int, str, str | None]] = []
    step = CHUNK_LINES - CHUNK_OVERLAP
    idx = 0
    for start in range(0, len(lines), step):
        window = lines[start : start + CHUNK_LINES]
        text = "\n".join(window).strip()
        if text:
            m = _SYMBOL_RE.search(text)
            chunks.append((idx, text, m.group(1) if m else None))
            idx += 1
        if start + CHUNK_LINES >= len(lines):
            break
    return chunks


def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


def ingest_repo(repo_name: str, root: Path) -> dict:
    stats = {
        "files_seen": 0, "files_changed": 0, "files_skipped": 0, "chunks_written": 0,
        "secrets_masked": 0,
    }

    with psycopg.connect(settings.tiger_database_url, autocommit=False) as conn:
        with conn.cursor() as cur:
            # Pass 1: detect changed files and collect their chunks. Embedding is
            # deferred so all chunks go out in as few API calls as possible — a
            # request-per-file would blow the free tier's 3 requests/minute cap.
            changed: list[tuple[str, str, list[tuple[int, str, str | None]]]] = []
            for path in iter_files(root):
                stats["files_seen"] += 1
                rel = path.relative_to(root).as_posix()
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue

                h = content_hash(content)
                if get_indexed_hash(cur, repo_name, rel) == h:
                    stats["files_skipped"] += 1
                    continue

                # Mask secrets in each chunk before it's embedded or stored - both
                # code_chunks.content and the vector sent to Voyage must be the masked
                # version (security/masking.py, threat_model.py threat #2).
                masked_chunks = []
                for chunk_index, text, symbol in chunk_text(content):
                    masked_text, hits = mask_secrets(text)
                    stats["secrets_masked"] += len(hits)
                    masked_chunks.append((chunk_index, masked_text, symbol))
                changed.append((rel, h, masked_chunks))

            # Pass 2: embed every collected chunk in one throttled, batched sweep.
            all_texts = [text for _, _, chunks in changed for _, text, _ in chunks]
            all_embeddings = embed_documents(all_texts, delay_s=21.0)

            # Pass 3: replace each file's chunks wholesale and record freshness.
            pos = 0
            for rel, h, chunks in changed:
                cur.execute(
                    "DELETE FROM code_chunks WHERE repo=%s AND path=%s", (repo_name, rel)
                )
                for chunk_index, text, symbol in chunks:
                    emb = all_embeddings[pos]
                    pos += 1
                    cur.execute(
                        """
                        INSERT INTO code_chunks
                            (repo, path, symbol, chunk_index, content, embedding, token_count)
                        VALUES (%s, %s, %s, %s, %s, %s::vector, %s)
                        """,
                        (repo_name, rel, symbol, chunk_index, text,
                         _vec_literal(emb), len(text) // 4),
                    )
                    stats["chunks_written"] += 1
                record_indexed(cur, repo_name, rel, h)
                stats["files_changed"] += 1

        conn.commit()
    return stats


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m backend.data.ingestion <repo_path> [repo_name]")
    root = Path(sys.argv[1]).resolve()
    if not root.is_dir():
        raise SystemExit(f"not a directory: {root}")
    repo_name = sys.argv[2] if len(sys.argv) > 2 else root.name

    print(f"Ingesting repo '{repo_name}' from {root}")
    stats = ingest_repo(repo_name, root)
    print(
        f"  files: {stats['files_seen']} seen, {stats['files_changed']} (re)embedded, "
        f"{stats['files_skipped']} unchanged\n"
        f"  chunks written: {stats['chunks_written']} "
        f"(secrets masked: {stats['secrets_masked']})"
    )


if __name__ == "__main__":
    main()
