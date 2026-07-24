"""Shared specialist-agent shape (Phase 8): retrieval -> (security only) static-analysis
tool -> LLM call -> structured-output parse -> Finding list. security_agent, quality_agent,
test_agent, and docs_agent are thin dispatchers over this one pipeline (agents/*_agent.py)
- they differ only in which AgentType they pass, which selects the domain prompt
(prompts/templates/<type>.md, Phase 5) and the routed model (tools/model_router, Phase 5).

BudgetGuard (Phase 16) and event emission into agent_events (Phase 10) plug in at the
marked points below; both are no-ops today since neither module is built yet, but the
pipeline is already shaped for them so wiring them in later doesn't restructure this file.

A specialist's own failure (bad JSON, network error, tool error) is caught and logged
rather than raised, so one agent's outage degrades to fewer findings, not a failed review
(ARCHITECTURE L8 - "the review still completes... rather than hanging forever")."""

from __future__ import annotations

import asyncio
import json
import logging

from backend.agents.contracts import Finding
from backend.memory.context_retriever import retrieve
from backend.models.enums import AgentType
from backend.orchestrator.state import ReviewState
from backend.prompts.registry import get_prompt
from backend.tools import capability_scope, model_router, tool_registry
from backend.tools.llm_client import complete

logger = logging.getLogger("agents")

_JSON_INSTRUCTIONS = """

Respond with ONLY a JSON array (no markdown fences, no prose before or after). Each
element is an object with exactly these keys: "category" (string), "summary" (string),
"file_path" (string), "line_start" (integer or null), "line_end" (integer or null),
"suggestion" (string or null), "confidence" (number between 0 and 1), "rationale"
(string), "severity" (one of "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO").
If there are no findings for this diff, respond with an empty JSON array: []
"""

_MAX_CONTEXT_CHUNKS = 5
_MAX_CHUNK_CHARS = 2000
_MAX_TOKENS = 3072


def _format_context(chunks: list[dict]) -> str:
    if not chunks:
        return "No related context was retrieved from the codebase."
    parts = []
    for c in chunks[:_MAX_CONTEXT_CHUNKS]:
        content = c["content"][:_MAX_CHUNK_CHARS]
        parts.append(f"--- {c['path']} (symbol: {c.get('symbol') or 'n/a'}) ---\n{content}")
    return "\n\n".join(parts)


def _parse_findings(agent_type: AgentType, raw_text: str) -> list[Finding]:
    """Extract a JSON array from the model's text and validate each item. A malformed
    item is dropped (logged), not allowed to fail the whole batch."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text

    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        logger.warning("agent=%s: no JSON array found in LLM output", agent_type.value)
        return []
    try:
        items = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        logger.warning("agent=%s: JSON parse failed: %s", agent_type.value, exc)
        return []

    findings: list[Finding] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item = dict(item)
        item["agent_type"] = agent_type.value  # never trust the model's own labeling
        try:
            findings.append(Finding(**item))
        except Exception as exc:  # noqa: BLE001 - one bad item shouldn't drop the batch
            logger.warning("agent=%s: dropping malformed finding: %s", agent_type.value, exc)
    return findings


async def run_specialist(agent_type: AgentType, state: ReviewState) -> list[Finding]:
    # --- BudgetGuard check (Phase 16 plugs in here; no-op until then) ---

    diff_text = state.get("diff") or ""
    repo = state.get("repo") or ""

    context_chunks: list[dict] = []
    if diff_text and repo:
        capability_scope.enforce(agent_type, "retrieve_context")
        try:
            context_chunks = await retrieve(repo, diff_text)
        except Exception as exc:  # noqa: BLE001 - retrieval outage shouldn't kill the agent
            logger.warning(
                "agent=%s: retrieval failed, continuing ungrounded: %s", agent_type.value, exc
            )

    lint_hits: list[str] = []
    if agent_type is AgentType.SECURITY and diff_text:
        lint_hits = capability_scope.call_tool(
            agent_type, "run_static_analysis", tool_registry.run_static_analysis, diff_text
        )

    user_parts = [f"PR diff:\n{diff_text or '(no diff provided)'}"]
    user_parts.append(f"\nRetrieved codebase context:\n{_format_context(context_chunks)}")
    if lint_hits:
        user_parts.append(
            "\nStatic analysis flagged these risky calls in the diff:\n"
            + "\n".join(f"- {h}" for h in lint_hits)
        )
    user_message = "\n".join(user_parts)

    system_prompt = get_prompt(agent_type.value) + _JSON_INSTRUCTIONS
    model = model_router.model_for(agent_type)

    logger.info("agent=%s model=%s: calling LLM", agent_type.value, model)
    try:
        # complete() is a blocking network call; keep the event loop free so the four
        # specialists actually run concurrently (ARCHITECTURE §3.2 parallel fan-out).
        result = await asyncio.to_thread(
            complete, model=model, system=system_prompt, user=user_message,
            max_tokens=_MAX_TOKENS,
        )
    except Exception as exc:  # noqa: BLE001 - one specialist's outage != a failed review
        logger.warning("agent=%s: LLM call failed: %s", agent_type.value, exc)
        return []

    findings = _parse_findings(agent_type, result.text)
    logger.info(
        "agent=%s model=%s tokens_in=%d tokens_out=%d findings=%d",
        agent_type.value, result.model, result.input_tokens, result.output_tokens,
        len(findings),
    )

    # --- event emission (Phase 10 plugs in here; logging above stands in for now) ---
    return findings
