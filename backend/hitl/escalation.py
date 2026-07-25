"""The routing rule (Phase 19): given the aggregator's decision and the deduped findings,
decide whether this review must go to a human instead of auto-posting.

CRITICAL findings ALWAYS escalate, regardless of the confidence-based decision (ADR-000:
"a CRITICAL security finding always escalates, even at 0.99 confidence"). This is a
belt-and-suspenders check - the Phase 8 gate already routes CRITICAL to awaiting_human -
but centralizing the rule here means the routing invariant is enforced in one named place
the worker calls, not implicitly trusted from the gate's output."""

from __future__ import annotations

from backend.models.enums import HITLReason, Severity


def should_route_to_human(
    decision: str | None, findings: list[dict]
) -> tuple[bool, str | None]:
    """Returns (route_to_human, reason). reason is a HITLReason value or None."""
    if any(f.get("severity") == Severity.CRITICAL.value for f in findings):
        return True, HITLReason.CRITICAL_FINDING.value
    if decision == "awaiting_human":
        return True, HITLReason.LOW_CONFIDENCE.value
    return False, None
