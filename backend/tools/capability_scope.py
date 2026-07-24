"""Enforces tool_registry.py's scope at call time (Phase 7). An agent attempting to call
a tool outside its declared scope - or a tool name that isn't registered at all - is
rejected here with a logged security event, never silently allowed or silently ignored.

The `event=` field in the log record is a stable key so Phase 10's observability spine
can later route this straight into agent_events without changing this module."""

from __future__ import annotations

import logging
from typing import Callable, TypeVar

from backend.core.exceptions import ToolScopeError
from backend.models.enums import AgentType
from backend.tools.tool_registry import is_allowed

logger = logging.getLogger("security.tool_scope")

T = TypeVar("T")


def enforce(agent_type: AgentType, tool_name: str) -> None:
    """Raise ToolScopeError (with a logged security event) if the call isn't permitted.
    Call this directly before awaiting an async tool (e.g. retrieval)."""
    if not is_allowed(agent_type, tool_name):
        logger.warning(
            "tool_scope_violation: agent=%s tool=%s",
            agent_type.value,
            tool_name,
            extra={
                "event": "tool_scope_violation",
                "agent_type": agent_type.value,
                "tool_name": tool_name,
            },
        )
        raise ToolScopeError(agent_type.value, tool_name)


def call_tool(
    agent_type: AgentType, tool_name: str, fn: Callable[..., T], *args, **kwargs
) -> T:
    """Enforce scope, then call a sync, in-process tool. The single choke point every
    registered sync tool call goes through."""
    enforce(agent_type, tool_name)
    return fn(*args, **kwargs)
