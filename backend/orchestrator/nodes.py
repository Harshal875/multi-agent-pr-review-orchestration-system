"""Graph node functions: build_context, the four specialist stubs, the fan-out dispatcher,
and aggregate.

Phase 4 keeps every node a stub - the point is to prove the topology (parallel fan-out)
and durability (checkpoint/resume), not real reasoning. Phase 8 replaces the specialist
bodies with real agents and the aggregate body with real merge/dedup.

Two test affordances live here deliberately:
  * each node appends to the file named by $EXEC_LOG (if set) so a test can prove which
    nodes actually executed across a crash/resume boundary;
  * aggregate raises early when $FAIL_AT_AGGREGATE is set, to simulate a mid-run crash
    after the specialists have already been checkpointed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from backend.config import settings
from backend.orchestrator.state import ReviewState

logger = logging.getLogger("orchestrator")

SPECIALISTS = ("security", "quality", "tests", "docs")
_SPECIALIST_WORK_SECONDS = 1.0  # long enough that overlapping timestamps prove parallelism


def _log_exec(node: str) -> None:
    ts = time.time()
    path = os.environ.get("EXEC_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{node}\t{ts:.3f}\n")
    logger.info("node=%s ts=%.3f", node, ts)


async def build_context(state: ReviewState) -> dict:
    """Stub grounding step. Phase 6 replaces this with hybrid retrieval."""
    _log_exec("build_context")
    return {"context": [f"<stub context for {state.get('repo')}#{state.get('pr_number')}>"]}


def _placeholder_finding(agent_type: str) -> dict:
    return {
        "agent_type": agent_type,
        "severity": "INFO",
        "category": "placeholder",
        "summary": f"{agent_type} stub finding",
        "file_path": "PLACEHOLDER",
        "line_start": None,
        "line_end": None,
        "suggestion": None,
        "confidence": 0.80,
        "rationale": f"Phase 4 stub - {agent_type} agent not yet implemented.",
    }


async def _run_specialist(agent_type: str, state: ReviewState) -> dict:
    _log_exec(f"specialist:{agent_type}")
    await asyncio.sleep(_SPECIALIST_WORK_SECONDS)  # simulate reasoning work
    return {"findings": [_placeholder_finding(agent_type)]}


async def security_node(state: ReviewState) -> dict:
    return await _run_specialist("security", state)


async def quality_node(state: ReviewState) -> dict:
    return await _run_specialist("quality", state)


async def tests_node(state: ReviewState) -> dict:
    return await _run_specialist("tests", state)


async def docs_node(state: ReviewState) -> dict:
    return await _run_specialist("docs", state)


async def aggregate(state: ReviewState) -> dict:
    """Stub aggregator applying the ADR-000 gate over placeholder findings."""
    if os.environ.get("FAIL_AT_AGGREGATE"):
        raise RuntimeError("injected crash at aggregate (specialists already checkpointed)")

    _log_exec("aggregate")
    findings = state.get("findings", [])
    confidences = [f["confidence"] for f in findings] or [0.0]
    overall = sum(confidences) / len(confidences)

    has_critical = any(f["severity"] == "CRITICAL" for f in findings)
    if has_critical:
        decision, reason = "awaiting_human", "critical_finding"
    elif overall < settings.confidence_threshold:
        decision, reason = "awaiting_human", "low_confidence"
    else:
        decision, reason = "post", None

    logger.info("aggregate: %d findings overall=%.3f -> %s", len(findings), overall, decision)
    return {"overall_confidence": overall, "decision": decision, "hitl_reason": reason}
