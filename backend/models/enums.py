"""Shared enums used across the truth lane, the Finding contract, and the HITL flow.
Values match the CHECK-comment vocabularies in scripts/migrations/2026-06-tiger-init.sql."""

from __future__ import annotations

from enum import Enum


class AgentType(str, Enum):
    SECURITY = "security"
    QUALITY = "quality"
    TESTS = "tests"
    DOCS = "docs"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    POSTED = "posted"
    AWAITING_HUMAN = "awaiting_human"
    REJECTED = "rejected"


class HITLReason(str, Enum):
    LOW_CONFIDENCE = "low_confidence"
    CRITICAL_FINDING = "critical_finding"


class HITLStatus(str, Enum):
    OPEN = "open"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"


class FeedbackVerdict(str, Enum):
    CONFIRMED = "confirmed"
    DISPUTED = "disputed"
    DISMISSED = "dismissed"
