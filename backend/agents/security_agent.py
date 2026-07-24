"""Security specialist: asks "could this be exploited?" - injection risks, secrets in
code, auth bypasses, unsafe deserialization. Thin dispatcher over agents/base_agent.py;
the domain prompt lives in prompts/templates/security.md and is the only thing that
differs between the four specialists. Built in Phase 8."""

from __future__ import annotations

from backend.agents.base_agent import run_specialist
from backend.agents.contracts import Finding
from backend.models.enums import AgentType
from backend.orchestrator.state import ReviewState


async def run(state: ReviewState) -> list[Finding]:
    return await run_specialist(AgentType.SECURITY, state)
