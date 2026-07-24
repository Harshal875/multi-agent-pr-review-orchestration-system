"""Shared specialist-agent shape (Phase 8): retrieval -> (security only) static-analysis
tool -> LLM call -> structured-output parse -> Finding list. security_agent, quality_agent,
test_agent, and docs_agent are thin dispatchers over this one pipeline (agents/*_agent.py)
- they differ only in which AgentType they pass, which selects the domain prompt
(prompts/templates/<type>.md, Phase 5) and the routed model (tools/model_router, Phase 5).

BudgetGuard (Phase 16) runs first, before any external call: if today's spend (read from
agent_health_1m) has already reached DAILY_BUDGET_USD, the agent stops here - no
retrieval, no tool call, no LLM call - and returns a Finding-free result with a
budget_exceeded span.end event, instead of spending further. Event emission
(Phase 10) is wired for real: every specialist run gets its own span (span.start/
span.end), with llm.call and (security-only) tool.call as nested sub-spans - both written
to agent_events via observability/events.py and mirrored as OTel spans via
observability/tracing.py, tagged with the ambient review_id from workflow_context.

A specialist's own failure (bad JSON, network error, tool error) is caught and logged
rather than raised, so one agent's outage degrades to fewer findings, not a failed review
(ARCHITECTURE L8 - "the review still completes... rather than hanging forever").

Security (Phase 11, security/threat_model.py): the diff is masked for secrets and
wrapped as untrusted content before anything downstream - retrieval, the lint tool, the
LLM call - ever sees it, so a hardcoded credential never reaches an external party and a
"ignore your instructions" comment is delimited as data, never obeyed as a command."""

from __future__ import annotations

import json
import logging
import time

from backend.agents.contracts import Finding
from backend.economics.budget import BudgetGuard
from backend.memory.context_retriever import retrieve
from backend.models.enums import AgentType
from backend.observability import workflow_context
from backend.observability.events import emit_agent_event, estimate_cost_usd
from backend.observability.tracing import traced_span
from backend.orchestrator.state import ReviewState
from backend.prompts.registry import get_prompt
from backend.reliability.circuit_breaker import CircuitOpenError
from backend.security.injection_guard import scan_for_injection, wrap_untrusted
from backend.security.masking import mask_secrets
from backend.tools import capability_scope, model_router, tool_registry
from backend.tools.llm_client import complete_async

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
    workflow_context.set_review_id(state["review_id"])

    with workflow_context.span() as (agent_span_id, agent_parent_span):
        with traced_span(f"agent.{agent_type.value}", agent=agent_type.value):
            t_agent0 = time.monotonic()
            await emit_agent_event(
                agent_type.value, "span.start",
                span_id=agent_span_id, parent_span=agent_parent_span,
            )

            budget = await BudgetGuard.check()
            if budget.blocked:
                logger.warning(
                    "agent=%s: daily budget exceeded ($%.4f >= $%.4f), skipping LLM call",
                    agent_type.value, budget.spent_usd, budget.cap_usd,
                )
                await emit_agent_event(
                    agent_type.value, "span.end",
                    span_id=agent_span_id, parent_span=agent_parent_span,
                    outcome="budget_exceeded",
                    latency_ms=int((time.monotonic() - t_agent0) * 1000),
                    payload={"spent_usd": budget.spent_usd, "cap_usd": budget.cap_usd},
                )
                return []

            diff_text = state.get("diff") or ""
            repo = state.get("repo") or ""

            # Mask secrets FIRST, before diff_text is used anywhere - retrieval, the
            # lint tool, and the LLM call all send this value to an external party, so
            # everything downstream must see the masked version (security/masking.py,
            # threat_model.py threat #2). Detect (not filter) injection-shaped phrasing
            # for the audit log; the actual defense is wrap_untrusted() below, applied
            # unconditionally when building the LLM prompt (threat #1).
            if diff_text:
                diff_text, masked_categories = mask_secrets(diff_text)
                if masked_categories:
                    logger.warning(
                        "agent=%s: masked %d secret(s) in diff: %s",
                        agent_type.value, len(masked_categories), masked_categories,
                    )
                injection_hits = scan_for_injection(diff_text)
                if injection_hits:
                    logger.warning(
                        "agent=%s: diff contains injection-shaped phrasing: %s",
                        agent_type.value, injection_hits,
                    )

            context_chunks: list[dict] = []
            if diff_text and repo:
                capability_scope.enforce(agent_type, "retrieve_context")
                try:
                    context_chunks = await retrieve(repo, diff_text)
                except Exception as exc:  # noqa: BLE001 - retrieval outage shouldn't kill the agent
                    logger.warning(
                        "agent=%s: retrieval failed, continuing ungrounded: %s",
                        agent_type.value, exc,
                    )

            lint_hits: list[str] = []
            if agent_type is AgentType.SECURITY and diff_text:
                with workflow_context.span() as (tool_span_id, tool_parent_span):
                    with traced_span("tool.call", tool_name="run_static_analysis"):
                        lint_hits = capability_scope.call_tool(
                            agent_type, "run_static_analysis",
                            tool_registry.run_static_analysis, diff_text,
                        )
                        await emit_agent_event(
                            agent_type.value, "tool.call",
                            span_id=tool_span_id, parent_span=tool_parent_span,
                            outcome="ok", payload={"tool_name": "run_static_analysis",
                                                    "hits": len(lint_hits)},
                        )

            diff_for_prompt = wrap_untrusted(diff_text) if diff_text else "(no diff provided)"
            user_parts = [f"PR diff:\n{diff_for_prompt}"]
            user_parts.append(
                f"\nRetrieved codebase context:\n{_format_context(context_chunks)}"
            )
            if lint_hits:
                user_parts.append(
                    "\nStatic analysis flagged these risky calls in the diff:\n"
                    + "\n".join(f"- {h}" for h in lint_hits)
                )
            user_message = "\n".join(user_parts)

            system_prompt = get_prompt(agent_type.value) + _JSON_INSTRUCTIONS
            model = model_router.model_for(agent_type)

            findings: list[Finding] = []
            with workflow_context.span() as (llm_span_id, llm_parent_span):
                with traced_span("llm.call", model=model):
                    logger.info("agent=%s model=%s: calling LLM", agent_type.value, model)
                    t_llm0 = time.monotonic()
                    try:
                        # complete_async retries transient failures with backoff and
                        # trips a shared circuit breaker after repeated ones
                        # (reliability/retry.py, circuit_breaker.py - Phase 12).
                        result = await complete_async(
                            model=model, system=system_prompt, user=user_message,
                            max_tokens=_MAX_TOKENS,
                        )
                    except CircuitOpenError as exc:
                        latency_ms = int((time.monotonic() - t_llm0) * 1000)
                        logger.warning(
                            "agent=%s: LLM circuit open, failing fast: %s", agent_type.value, exc
                        )
                        await emit_agent_event(
                            agent_type.value, "llm.call",
                            span_id=llm_span_id, parent_span=llm_parent_span,
                            model=model, latency_ms=latency_ms, outcome="circuit_open",
                            payload={"error": str(exc)},
                        )
                    except Exception as exc:  # noqa: BLE001 - one specialist's outage != a failed review
                        latency_ms = int((time.monotonic() - t_llm0) * 1000)
                        logger.warning("agent=%s: LLM call failed: %s", agent_type.value, exc)
                        await emit_agent_event(
                            agent_type.value, "llm.call",
                            span_id=llm_span_id, parent_span=llm_parent_span,
                            model=model, latency_ms=latency_ms, outcome="error",
                            payload={"error": str(exc)},
                        )
                    else:
                        latency_ms = int((time.monotonic() - t_llm0) * 1000)
                        findings = _parse_findings(agent_type, result.text)
                        cost = estimate_cost_usd(
                            result.model, result.input_tokens, result.output_tokens
                        )
                        logger.info(
                            "agent=%s model=%s tokens_in=%d tokens_out=%d findings=%d",
                            agent_type.value, result.model, result.input_tokens,
                            result.output_tokens, len(findings),
                        )
                        await emit_agent_event(
                            agent_type.value, "llm.call",
                            span_id=llm_span_id, parent_span=llm_parent_span,
                            model=result.model, tokens_in=result.input_tokens,
                            tokens_out=result.output_tokens, cost_usd=cost,
                            latency_ms=latency_ms, outcome="ok",
                        )

            total_latency_ms = int((time.monotonic() - t_agent0) * 1000)
            avg_confidence = (
                sum(f.confidence for f in findings) / len(findings) if findings else None
            )
            await emit_agent_event(
                agent_type.value, "span.end",
                span_id=agent_span_id, parent_span=agent_parent_span,
                outcome="ok", confidence=avg_confidence, latency_ms=total_latency_ms,
                payload={"findings_count": len(findings)},
            )

    return findings
