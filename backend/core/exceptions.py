"""Shared exception types used across modules (e.g. BudgetExceeded, RetrievalTimeout,
WorkflowNodeTimeout). Kept dependency-free (no imports from models/ or elsewhere) so any
module can import from core without creating a cycle."""

from __future__ import annotations


class ToolScopeError(Exception):
    """Raised when an agent calls a tool outside its declared scope, or a tool name that
    isn't registered at all (Phase 7). Plain-string fields, not the AgentType enum, to
    keep this module import-free per the core/ dependency rule (ADR-002)."""

    def __init__(self, agent_type: str, tool_name: str) -> None:
        self.agent_type = agent_type
        self.tool_name = tool_name
        super().__init__(
            f"agent '{agent_type}' is not permitted to call tool '{tool_name}'"
        )
