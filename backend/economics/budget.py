"""BudgetGuard.check() - called at the top of every agent run in base_agent.py;
hard-blocks further LLM calls once the daily cap (DAILY_BUDGET_USD) is exceeded
(ADR-004). Built in Phase 16."""
