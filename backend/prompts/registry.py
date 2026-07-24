"""Versioned prompt registry. One markdown template per agent under templates/, loaded
by name at call time (read from disk each call, so swapping a template file changes agent
behavior with no code change — the Phase 5 gate). Versioning is by git history + filename;
a future revision can add e.g. security.v2.md and switch the name a router asks for."""

from __future__ import annotations

from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent / "templates"


def get_prompt(name: str) -> str:
    path = TEMPLATES / f"{name}.md"
    if not path.exists():
        raise KeyError(f"no prompt template named {name!r} in {TEMPLATES}")
    return path.read_text(encoding="utf-8")


def list_prompts() -> list[str]:
    return sorted(p.stem for p in TEMPLATES.glob("*.md"))
