"""Wires the review StateGraph.

START -> build_context -> (Send fan-out to 4 specialists in parallel) -> aggregate -> END.

The four specialists run concurrently in one superstep: build_context's conditional edge
returns a list of Send commands (the LangGraph Send API, ARCHITECTURE §3.2), one per
specialist. aggregate has an incoming edge from each specialist, so LangGraph's join waits
for all four before it runs. The graph is returned uncompiled so the engine can compile it
with a Redis checkpointer."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from backend.orchestrator.nodes import (
    SPECIALISTS,
    aggregate,
    build_context,
    docs_node,
    quality_node,
    security_node,
    tests_node,
)
from backend.orchestrator.state import ReviewState

_SPECIALIST_NODES = {
    "security": security_node,
    "quality": quality_node,
    "tests": tests_node,
    "docs": docs_node,
}


def _fan_out(state: ReviewState) -> list[Send]:
    """Dispatch the same state to all four specialist nodes concurrently."""
    return [Send(name, state) for name in SPECIALISTS]


def build_graph() -> StateGraph:
    builder = StateGraph(ReviewState)

    builder.add_node("build_context", build_context)
    for name, fn in _SPECIALIST_NODES.items():
        builder.add_node(name, fn)
    builder.add_node("aggregate", aggregate)

    builder.add_edge(START, "build_context")
    builder.add_conditional_edges("build_context", _fan_out, list(SPECIALISTS))
    for name in SPECIALISTS:
        builder.add_edge(name, "aggregate")
    builder.add_edge("aggregate", END)

    return builder
