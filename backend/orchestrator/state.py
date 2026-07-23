"""The typed state that flows through the review graph.

`findings` carries an additive reducer (operator.add) because the four specialist nodes
write to it concurrently in a single LangGraph superstep - the reducer merges their
partial lists instead of letting parallel writes clobber each other. In Phase 4 a finding
is a placeholder dict; Phase 8 replaces it with the agents/contracts.py Finding model."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class ReviewState(TypedDict, total=False):
    # Identity + inputs
    review_id: str
    repo: str
    pr_number: int
    commit_sha: str
    diff: str

    # Grounding (Phase 6 fills this from retrieval; stubbed now)
    context: list[Any]

    # Fan-out output: concurrently written, reducer-merged
    findings: Annotated[list[dict], operator.add]

    # Aggregator output
    overall_confidence: float | None
    decision: str | None          # post | awaiting_human
    hitl_reason: str | None       # low_confidence | critical_finding
