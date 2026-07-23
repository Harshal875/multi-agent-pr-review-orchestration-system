"""Abstract orchestration interface (ADR-001).

All orchestrator/worker code depends on this contract, never on LangGraph directly, so a
future engine (e.g. Temporal) can be swapped in by implementing these three methods alone.
The concrete LangGraph implementation lives in orchestrator/langgraph_engine.py.

workflow_id is the review_id, used as the checkpoint thread_id so a crashed run resumes
from its last completed node."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class WorkflowEngine(ABC):
    @abstractmethod
    async def run(self, workflow_id: str, input: dict[str, Any]) -> dict[str, Any]:
        """Start a workflow from the given input and run it to completion."""

    @abstractmethod
    async def resume(
        self, workflow_id: str, state: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Resume a previously-checkpointed workflow from where it stopped."""

    @abstractmethod
    async def get_state(self, workflow_id: str) -> dict[str, Any] | None:
        """Return the current checkpointed state (values + pending next nodes)."""
