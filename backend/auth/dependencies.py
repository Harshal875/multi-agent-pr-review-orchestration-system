"""FastAPI dependencies wrapping security/rbac.py's role model - who can read reviews,
who can approve or dispute HITL findings.

Unwired today, same reason as rbac.py itself: the approve/dispute routes this exists to
gate don't exist until Phase 19. require_role() reads the caller's role from an
X-User-Role header - a placeholder for whatever real auth/session mechanism eventually
issues an authenticated identity; there is no login/session system in this project yet.
Replace _resolve_role()'s header read with real session/token verification when one
exists; require_role()'s signature and the routes that use it don't need to change."""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from backend.security.rbac import Role, check_role


def _resolve_role(x_user_role: str | None) -> Role:
    if x_user_role is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing X-User-Role"
        )
    try:
        return Role(x_user_role)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"unknown role '{x_user_role}'",
        )


def require_role(required: Role):
    """FastAPI dependency factory: Depends(require_role(Role.APPROVER)) on a route."""

    def dependency(x_user_role: str | None = Header(default=None)) -> Role:
        actual = _resolve_role(x_user_role)
        if not check_role(actual, required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"role '{actual.value}' cannot perform an action requiring "
                       f"'{required.value}'",
            )
        return actual

    return dependency
