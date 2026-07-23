"""Pydantic response shapes for the api/ routers. Kept separate from the domain models
in models/ so the API surface can evolve independently of internal contracts."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    review_id: uuid.UUID
    agent_type: str
    severity: str
    category: str
    summary: str
    file_path: str
    line_start: int | None
    line_end: int | None
    suggestion: str | None
    confidence: float
    rationale: str
    duplicate_of: uuid.UUID | None
    created_at: dt.datetime


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repo: str
    pr_number: int
    commit_sha: str
    delivery_id: str
    status: str
    overall_confidence: float | None
    github_review_id: str | None
    created_at: dt.datetime
    posted_at: dt.datetime | None
