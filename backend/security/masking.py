"""Strips anything that looks like a secret/API key from diffs before they're embedded
or sent to an LLM (security/threat_model.py, threat #2). Two pattern groups:

  - Whole-match patterns for vendor key formats with a distinctive shape (AWS, GitHub,
    OpenAI/Anthropic/Groq/Voyage-style "sk-"/"gsk_"/"pa-" keys, PEM private key blocks) -
    the entire matched token is redacted.
  - An assigned-secret pattern for `api_key = "..."` / `token: "..."` style code, where
    the variable name is kept (so "this line hardcodes a credential" stays visible and
    reviewable) and only the quoted value is redacted.

Wired into agents/base_agent.py (masks the diff before retrieval, the static-analysis
tool, or the LLM call - all three send it to an external party) and data/ingestion.py
(masks file content before it's embedded and stored in code_chunks)."""

from __future__ import annotations

import re

_REDACTED = "[REDACTED_SECRET]"

_WHOLE_MATCH_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("sk_style_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),  # OpenAI/Anthropic-shaped
    ("groq_key", re.compile(r"\bgsk_[A-Za-z0-9]{20,}\b")),
    ("voyage_key", re.compile(r"\bpa-[A-Za-z0-9_-]{20,}\b")),
    ("private_key_block", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
    )),
]

_ASSIGNED_SECRET_PATTERN = re.compile(
    r"""(?i)\b(api[_-]?key|secret|token|password|passwd|access[_-]?key)(\s*[:=]\s*)"""
    r"""["']([A-Za-z0-9_\-/+=]{8,})["']"""
)


def mask_secrets(text: str) -> tuple[str, list[str]]:
    """Returns (masked_text, categories_matched). Redacts secret *values*; surrounding
    code structure (variable names, assignment syntax) is preserved."""
    matched: list[str] = []
    masked = text

    for name, pattern in _WHOLE_MATCH_PATTERNS:
        def _redact_whole(m: re.Match, name: str = name) -> str:
            matched.append(name)
            return _REDACTED
        masked = pattern.sub(_redact_whole, masked)

    def _redact_assigned(m: re.Match) -> str:
        matched.append("assigned_secret")
        return f'{m.group(1)}{m.group(2)}"{_REDACTED}"'
    masked = _ASSIGNED_SECRET_PATTERN.sub(_redact_assigned, masked)

    return masked, matched
