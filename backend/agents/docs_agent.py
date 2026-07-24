"""Docs specialist: asks "will the next reader understand?" - missing docstrings,
outdated comments, undocumented public APIs. Thin dispatcher over agents/base_agent.py;
the domain prompt lives in prompts/templates/docs.md. Built in Phase 8."""

from __future__ import annotations

from backend.agents.base_agent import run_specialist
from backend.agents.contracts import Finding
from backend.models.enums import AgentType
from backend.orchestrator.state import ReviewState


async def run(state: ReviewState) -> list[Finding]:
    return await run_specialist(AgentType.DOCS, state)
