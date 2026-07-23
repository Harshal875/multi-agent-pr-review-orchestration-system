"""Minimal Pydantic models for the slices of the GitHub pull_request webhook payload we
read. Deliberately partial - GitHub sends far more; we model only what the parser needs.
Extended as later phases (posting reviews, fetching diffs) require more fields."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Repository(BaseModel):
    full_name: str  # "owner/name"


class PRHead(BaseModel):
    sha: str


class PullRequest(BaseModel):
    number: int
    title: str | None = None
    head: PRHead
    draft: bool = False


class PullRequestEvent(BaseModel):
    action: str
    repository: Repository
    pull_request: PullRequest = Field(alias="pull_request")

    model_config = {"populate_by_name": True}
