"""Parses a raw GitHub pull_request payload into the internal WebhookEvent contract.

Only actionable actions produce an event; everything else (labeled, assigned, closed,
draft PRs, etc.) returns None so the router can ack-and-ignore. 'synchronize' means new
commits were pushed to an open PR - we re-review those."""

from __future__ import annotations

from backend.integrations.github_models import PullRequestEvent
from backend.models.webhook import WebhookEvent

ACTIONABLE = {"opened", "synchronize", "reopened", "ready_for_review"}


def parse_pull_request_event(payload: dict, delivery_id: str) -> WebhookEvent | None:
    action = payload.get("action")
    if action not in ACTIONABLE:
        return None

    event = PullRequestEvent.model_validate(payload)

    # Skip draft PRs unless they were just marked ready.
    if event.pull_request.draft and action != "ready_for_review":
        return None

    return WebhookEvent(
        delivery_id=delivery_id,
        action=event.action,
        repo=event.repository.full_name,
        pr_number=event.pull_request.number,
        commit_sha=event.pull_request.head.sha,
        title=event.pull_request.title,
    )
