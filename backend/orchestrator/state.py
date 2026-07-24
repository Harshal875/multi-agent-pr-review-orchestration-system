"""The typed state that flows through the review graph.

`findings` carries an additive reducer (operator.add) because the four specialist nodes
write to it concurrently in a single LangGraph superstep - the reducer merges their
partial lists instead of letting parallel writes clobber each other. Each finding is a
dict (Finding.model_dump(mode="json")) so the state stays plain-JSON-serializable for the
Redis checkpointer.

`deduped_findings` is the aggregator's output and is NOT reduced (plain overwrite) -
aggregate is the only writer, and it must replace, not append to, the raw list. Retrieval
is per-specialist (Phase 6/8), not a separate build_context step, so there is no shared
`context` field on this state."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class ReviewState(TypedDict, total=False):
    # Identity + inputs
    review_id: str
    repo: str
    pr_number: int
    commit_sha: str
    diff: str

    # Fan-out output: concurrently written, reducer-merged
    findings: Annotated[list[dict], operator.add]

    # Aggregator output
    deduped_findings: list[dict]
    overall_confidence: float | None
    decision: str | None          # post | awaiting_human
    hitl_reason: str | None       # low_confidence | critical_finding
