"""Role model and role-check logic for who can approve/dispute HITL findings and access
dashboard routes (security/threat_model.py, threat #4). Framework-agnostic - FastAPI-
specific wiring (extracting the caller's role from a request) lives in
auth/dependencies.py, which calls check_role() from here.

Unwired today: Phase 3 only shipped read-only GET routes over review data; the
approve/dispute actions this module exists to gate don't exist until Phase 19 (HITL).
Building a role check against a target that doesn't exist yet would be theater, not
security - same honest-gap pattern as tools/sandbox.py in Phase 7 (a real, tested
primitive, wired in once its target exists). Phase 19 should apply
Depends(require_role(Role.APPROVER)) (auth/dependencies.py) to its new endpoints."""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    VIEWER = "viewer"      # can read reviews/findings
    APPROVER = "approver"  # can approve/dispute HITL findings
    ADMIN = "admin"        # full access, including RBAC/budget config


# A role satisfies a route requiring a *weaker* role too - approver/admin can do
# anything a viewer-gated route allows, admin can do anything an approver-gated route
# allows.
_IMPLIES: dict[Role, set[Role]] = {
    Role.VIEWER: {Role.VIEWER, Role.APPROVER, Role.ADMIN},
    Role.APPROVER: {Role.APPROVER, Role.ADMIN},
    Role.ADMIN: {Role.ADMIN},
}


def check_role(actual: Role, required: Role) -> bool:
    """True if a caller with `actual` role satisfies a route requiring `required`."""
    return actual in _IMPLIES[required]
