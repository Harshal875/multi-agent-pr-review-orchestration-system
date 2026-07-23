"""Routes each agent's LLM calls to a model tier by task type (cheap/fast for docs,
stronger for security) via a simple rule table, informed by economics/routing_advisor.py.
Built in Phase 5."""
