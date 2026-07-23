"""Abstract orchestration interface: run(workflow_id, input), resume(workflow_id, state),
get_state(workflow_id). All orchestrator code depends on this interface, never on LangGraph
directly, so a future engine (e.g. Temporal) can be swapped in by implementing this contract
alone (see docs/adr/ADR-001-langgraph-vs-temporal.md). Implemented in Phase 4."""
