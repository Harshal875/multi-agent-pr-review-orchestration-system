"""Shared exception types used across modules (e.g. BudgetExceeded, RetrievalTimeout,
WorkflowNodeTimeout). Kept dependency-free so any module can import from core without
creating a cycle. Populated as the phases that need them are built."""
