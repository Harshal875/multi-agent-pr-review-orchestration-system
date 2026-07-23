"""The Finding contract (Pydantic model): agent_type, severity, category, summary,
file_path, line_start/line_end, suggestion, confidence, rationale. Every specialist
agent returns list[Finding]; the aggregator merges across all four. Built in Phase 8."""
