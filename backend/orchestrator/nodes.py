"""Graph node functions: build_context (fan-out trigger), the four real specialist
nodes, and aggregate (merge/dedup/score/HITL-gate).

Phase 4 proved the topology (parallel fan-out) and durability (checkpoint/resume) with
placeholder specialists. Phase 8 replaces the specialist bodies with the real agents
(agents/*_agent.py -> agents/base_agent.py: retrieval -> LLM -> Finding parse) and
aggregate with real cross-agent dedup, keeping the same EXEC_LOG/FAIL_AT_AGGREGATE test
affordances the Phase 4 regression test depends on:
  * each node appends to the file named by $EXEC_LOG (if set) so a test can prove which
    nodes actually executed across a crash/resume boundary;
  * aggregate raises early when $FAIL_AT_AGGREGATE is set, to simulate a mid-run crash
    after the specialists have already been checkpointed.
"""

from __future__ import annotations

import logging
import os
import time

from backend.agents import docs_agent, quality_agent, security_agent, test_agent
from backend.config import settings
from backend.observability import workflow_context
from backend.observability.events import emit_agent_event
from backend.observability.tracing import traced_span
from backend.orchestrator.state import ReviewState
from backend.reliability.timeout import with_timeout

logger = logging.getLogger("orchestrator")

SPECIALISTS = ("security", "quality", "tests", "docs")
_AGENT_MODULES = {
    "security": security_agent,
    "quality": quality_agent,
    "tests": test_agent,
    "docs": docs_agent,
}

# Hard per-node ceilings (Phase 12) so the aggregator can never wait forever on one
# stalled agent. 60s covers a slow LLM call plus its own internal retries+backoff
# (complete_async already retries up to 3x - this timeout is the outer backstop, not
# a substitute for it). A timed-out specialist degrades to zero findings, same as any
# other specialist failure (base_agent.py already treats that as a normal outcome).
_SPECIALIST_TIMEOUT_S = 60.0
_BUILD_CONTEXT_TIMEOUT_S = 10.0
_AGGREGATE_TIMEOUT_S = 30.0


def _log_exec(node: str) -> None:
    ts = time.time()
    path = os.environ.get("EXEC_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{node}\t{ts:.3f}\n")
    logger.info("node=%s ts=%.3f", node, ts)


@with_timeout(_BUILD_CONTEXT_TIMEOUT_S, default={})
async def build_context(state: ReviewState) -> dict:
    """Fan-out trigger node. Retrieval happens per-specialist (Phase 6/8), not here, so
    this node has no work of its own beyond marking that the graph started."""
    _log_exec("build_context")
    return {}


async def _run_specialist_node(name: str, state: ReviewState) -> dict:
    _log_exec(f"specialist:{name}")
    findings = await _AGENT_MODULES[name].run(state)
    return {"findings": [f.model_dump(mode="json") for f in findings]}


@with_timeout(_SPECIALIST_TIMEOUT_S, default={"findings": []})
async def security_node(state: ReviewState) -> dict:
    return await _run_specialist_node("security", state)


@with_timeout(_SPECIALIST_TIMEOUT_S, default={"findings": []})
async def quality_node(state: ReviewState) -> dict:
    return await _run_specialist_node("quality", state)


@with_timeout(_SPECIALIST_TIMEOUT_S, default={"findings": []})
async def tests_node(state: ReviewState) -> dict:
    return await _run_specialist_node("tests", state)


@with_timeout(_SPECIALIST_TIMEOUT_S, default={"findings": []})
async def docs_node(state: ReviewState) -> dict:
    return await _run_specialist_node("docs", state)


def _line_range(f: dict) -> tuple[int, int] | None:
    start = f.get("line_start")
    if start is None:
        return None
    end = f.get("line_end") if f.get("line_end") is not None else start
    return start, end


def _overlaps(a: dict, b: dict) -> bool:
    """Two findings are the "same issue" for dedup purposes only if they're on the same
    file with overlapping line ranges. A finding with no line range (whole-file) is never
    auto-merged - there's no range to compare, so merging would risk collapsing two
    genuinely different whole-file findings into one."""
    if a["file_path"] != b["file_path"]:
        return False
    ra, rb = _line_range(a), _line_range(b)
    if ra is None or rb is None:
        return False
    return ra[0] <= rb[1] and rb[0] <= ra[1]


def _dedup(findings: list[dict]) -> list[dict]:
    """Merge findings multiple agents raised on the same file/overlapping lines, keeping
    the highest-confidence one and recording which agents agreed (ARCHITECTURE §3.4)."""
    kept: list[dict] = []
    for f in findings:
        match = next((k for k in kept if _overlaps(f, k)), None)
        if match is None:
            merged = dict(f)
            merged["agreed_by"] = [f["agent_type"]]
            kept.append(merged)
            continue
        match["agreed_by"] = sorted(set(match["agreed_by"]) | {f["agent_type"]})
        if f["confidence"] > match["confidence"]:
            agreed_by = match["agreed_by"]
            match.clear()
            match.update(f)
            match["agreed_by"] = agreed_by
    return kept


@with_timeout(
    _AGGREGATE_TIMEOUT_S,
    # Conservative-by-construction: if aggregation itself somehow doesn't finish (it
    # has no external calls beyond one event write, so this should be rare), never
    # guess "post" - force a human to look rather than risk auto-posting an incomplete
    # or unscored result.
    default={
        "deduped_findings": [], "overall_confidence": None,
        "decision": "awaiting_human", "hitl_reason": "aggregation_timeout",
    },
)
async def aggregate(state: ReviewState) -> dict:
    """Merge the four specialists' findings, dedup, score, and apply the ADR-000
    confidence-weighted HITL gate."""
    if os.environ.get("FAIL_AT_AGGREGATE"):
        raise RuntimeError("injected crash at aggregate (specialists already checkpointed)")

    _log_exec("aggregate")
    raw_findings = state.get("findings", [])
    deduped = _dedup(raw_findings)

    confidences = [f["confidence"] for f in deduped] or [0.0]
    overall = sum(confidences) / len(confidences)
    has_critical = any(f["severity"] == "CRITICAL" for f in deduped)

    if has_critical:
        decision, reason = "awaiting_human", "critical_finding"
    elif overall < settings.confidence_threshold:
        decision, reason = "awaiting_human", "low_confidence"
    else:
        decision, reason = "post", None

    logger.info(
        "aggregate: %d raw -> %d deduped, overall=%.3f -> %s",
        len(raw_findings), len(deduped), overall, decision,
    )

    workflow_context.set_review_id(state["review_id"])
    with workflow_context.span() as (span_id, parent_span):
        with traced_span("decision", decision=decision):
            await emit_agent_event(
                "aggregator", "decision",
                span_id=span_id, parent_span=parent_span,
                outcome=decision, confidence=overall,
                payload={
                    "hitl_reason": reason,
                    "raw_count": len(raw_findings),
                    "deduped_count": len(deduped),
                },
            )

    return {
        "deduped_findings": deduped,
        "overall_confidence": overall,
        "decision": decision,
        "hitl_reason": reason,
    }
