"""Wires the LangGraph StateGraph and uses the Send API for the four-way parallel
fan-out to the specialist agent nodes, checkpointing to Redis at each node boundary.
Built in Phase 4."""
