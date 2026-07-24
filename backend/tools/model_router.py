"""Per-agent model routing (Phase 5). Maps each concern to a model by the ADR-000 stakes:
the security agent gets the strongest model, docs the cheapest/fastest. Agents ask the
router for their model — they never hardcode a model string, so re-routing one agent is a
one-line change here (the Phase 5 gate). Phase 16's routing_advisor can later tune these
from observed cost/latency.

Models are Groq's (see provider-split memory) — verified against Groq's /models list."""

from __future__ import annotations

from backend.models.enums import AgentType

# Stronger model where the consequence of a miss is highest (security/quality/tests),
# cheaper/faster where it is lowest (docs). gpt-oss-120b is a reasoning model — it spends
# output tokens on hidden reasoning before the final answer, so callers must budget
# max_tokens generously (verified: needs several hundred, not the ~20 a plain chat model
# would use for a one-line reply).
_STRONG = "openai/gpt-oss-120b"
_FAST = "llama-3.1-8b-instant"

_ROUTES: dict[AgentType, str] = {
    AgentType.SECURITY: _STRONG,
    AgentType.QUALITY: _STRONG,
    AgentType.TESTS: _STRONG,
    AgentType.DOCS: _FAST,
}
_DEFAULT_MODEL = _STRONG


def model_for(agent_type: AgentType) -> str:
    return _ROUTES.get(agent_type, _DEFAULT_MODEL)


def set_route(agent_type: AgentType, model: str) -> None:
    """Re-point one agent at a different model at runtime (used by tests / the advisor)."""
    _ROUTES[agent_type] = model


def routes() -> dict[AgentType, str]:
    return dict(_ROUTES)
