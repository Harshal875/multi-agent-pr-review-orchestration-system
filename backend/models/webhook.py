"""The normalized shape the webhook parser produces from a GitHub pull_request payload.
This is the internal contract the rest of the pipeline consumes - not the raw GitHub JSON
(that lives in integrations/github_models.py)."""

from __future__ import annotations

from pydantic import BaseModel


class WebhookEvent(BaseModel):
    """One actionable pull_request event, already validated and flattened."""

    delivery_id: str          # X-GitHub-Delivery UUID - the idempotency key
    action: str               # opened | synchronize | reopened | ready_for_review
    repo: str                 # owner/name
    pr_number: int
    commit_sha: str           # head SHA at the time of the event
    title: str | None = None
