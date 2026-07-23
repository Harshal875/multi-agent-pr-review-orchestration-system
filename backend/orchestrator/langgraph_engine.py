"""LangGraph implementation of core.workflow_engine.WorkflowEngine (ADR-001).

This is the ONLY module that imports LangGraph's engine surface directly. It owns the
Redis checkpointer (AsyncRedisSaver) so a worker crash mid-review resumes from the last
completed node - the checkpoint store is the same Redis that backs the ARQ queue
(ARCHITECTURE §3.2). Lazy async init handles the one-time index setup (asetup)."""

from __future__ import annotations

import asyncio
from typing import Any

from langgraph.checkpoint.redis.aio import AsyncRedisSaver

from backend.config import settings
from backend.core.workflow_engine import WorkflowEngine
from backend.orchestrator.graph import build_graph


class LangGraphEngine(WorkflowEngine):
    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url or settings.redis_url
        self._graph = None
        self._saver: AsyncRedisSaver | None = None
        self._lock = asyncio.Lock()

    async def _ensure(self) -> None:
        if self._graph is not None:
            return
        async with self._lock:
            if self._graph is not None:
                return
            saver = AsyncRedisSaver(redis_url=self._redis_url)
            await saver.asetup()
            self._saver = saver
            self._graph = build_graph().compile(checkpointer=saver)

    @staticmethod
    def _config(workflow_id: str) -> dict:
        return {"configurable": {"thread_id": workflow_id}}

    async def run(self, workflow_id: str, input: dict[str, Any]) -> dict[str, Any]:
        await self._ensure()
        return await self._graph.ainvoke(input, self._config(workflow_id))

    async def resume(
        self, workflow_id: str, state: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        await self._ensure()
        # Passing None resumes from the latest checkpoint for this thread_id.
        return await self._graph.ainvoke(state, self._config(workflow_id))

    async def get_state(self, workflow_id: str) -> dict[str, Any] | None:
        await self._ensure()
        snapshot = await self._graph.aget_state(self._config(workflow_id))
        if snapshot is None:
            return None
        return {"values": snapshot.values, "next": list(snapshot.next)}


_engine: LangGraphEngine | None = None


def get_engine() -> LangGraphEngine:
    """Process-wide singleton, used by the ARQ worker."""
    global _engine
    if _engine is None:
        _engine = LangGraphEngine()
    return _engine
