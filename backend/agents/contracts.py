"""The Finding contract: every specialist agent returns list[Finding]; the aggregator
merges across all four. Field set matches finding_records (scripts/migrations/2026-06-
tiger-init.sql) so a future persistence step is a straight field-for-field mapping."""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.models.enums import AgentType, Severity


class Finding(BaseModel):
    agent_type: AgentType
    severity: Severity
    category: str
    summary: str
    file_path: str
    line_start: int | None = None
    line_end: int | None = None
    suggestion: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
