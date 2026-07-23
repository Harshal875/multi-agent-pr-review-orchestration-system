"""Shared specialist-agent shape: BudgetGuard check -> retrieval call -> LLM call ->
structured-output parse -> event emission -> error handling. security_agent, quality_agent,
test_agent, and docs_agent each subclass this and differ only in domain prompt and
post-processing. Built out in Phase 8."""
