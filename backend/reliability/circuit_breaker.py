"""Circuit breaker for external calls (GitHub API, LLM provider) so a stalled
dependency degrades gracefully instead of hanging the pipeline. Built in Phase 12."""
