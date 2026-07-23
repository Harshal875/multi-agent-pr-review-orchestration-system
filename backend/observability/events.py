"""emit_agent_event() - writes one row per action (span start/end, llm.call, tool.call,
decision) into the agent_events hypertable. The single write path feeding the trace
viewer, audit trail, and cost ledger. Built in Phase 10."""
