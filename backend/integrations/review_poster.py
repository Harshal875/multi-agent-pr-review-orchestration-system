"""Shared "format the findings into a review and post it to GitHub" path (Phase 19),
used by BOTH the auto-post decision (job_queue/arq_worker.py) and the HITL approve
endpoint (hitl/feedback.py) - so the markdown format and the mark-posted bookkeeping
live in exactly one place, not duplicated across the two callers.

Posts as a COMMENT review (not REQUEST_CHANGES/APPROVE): the agent surfaces findings for
a human to judge; it does not itself block or bless a merge. On success the review row is
marked status='posted' with the returned github_review_id, so pr_review_records finally
reflects reality (before Phase 19 nothing ever set 'posted' - see repository.py)."""

from __future__ import annotations

import uuid

from backend.database import repository
from backend.database.models import FindingRecord, PRReviewRecord
from backend.integrations.github_client import get_github_client

_SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
_SEVERITY_EMOJI = {
    "CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵", "INFO": "⚪",
}


def format_review_body(review: PRReviewRecord, findings: list[FindingRecord]) -> str:
    if not findings:
        return (
            "## 🤖 AI PR Review\n\nNo issues found across the security, quality, tests, "
            "and documentation specialists."
        )
    conf = review.overall_confidence
    header = (
        f"## 🤖 AI PR Review\n\n"
        f"**{len(findings)} finding(s)** across security / quality / tests / docs"
        + (f" · overall confidence **{float(conf):.2f}**" if conf is not None else "")
        + "\n"
    )
    ordered = sorted(
        findings, key=lambda f: (_SEVERITY_ORDER.get(f.severity, 9), -float(f.confidence))
    )
    lines = [header]
    for f in ordered:
        loc = f.file_path
        if f.line_start is not None:
            loc += f":{f.line_start}" + (f"-{f.line_end}" if f.line_end else "")
        emoji = _SEVERITY_EMOJI.get(f.severity, "")
        lines.append(
            f"\n### {emoji} {f.severity} · {f.agent_type} · `{loc}`\n"
            f"**{f.summary}**\n\n"
            f"{f.rationale}\n"
            + (f"\n**Suggestion:** {f.suggestion}\n" if f.suggestion else "")
            + f"\n_confidence: {float(f.confidence):.2f}_\n"
        )
    lines.append(
        "\n---\n_Posted by the AI PR-review agent. Reply or dispute individual findings "
        "if any are off-base._"
    )
    return "\n".join(lines)


async def post_review_for(session, review_id: uuid.UUID) -> str:
    """Format this review's findings and post them to the PR, then mark it posted.
    Returns the GitHub review id. Raises if the review row is missing or the post fails
    (callers treat a raise as 'not posted', leaving status unchanged)."""
    review = await repository.get_review(session, review_id)
    if review is None:
        raise ValueError(f"no review row for {review_id}")
    findings = list(await repository.get_findings(session, review_id))

    body = format_review_body(review, findings)
    github_review_id = await get_github_client().post_review(
        review.repo, review.pr_number, body, event="COMMENT"
    )
    await repository.mark_review_posted(session, review_id, github_review_id)
    return github_review_id
