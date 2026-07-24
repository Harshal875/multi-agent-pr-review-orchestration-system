"""Phase 7 DoD: an agent calling a tool outside its declared scope is rejected with a
logged security event, not silently allowed - and neither is a call to an unregistered
tool name, for anyone.

Run: python scripts/phase7_tool_scope_test.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.exceptions import ToolScopeError            # noqa: E402
from backend.models.enums import AgentType                    # noqa: E402
from backend.tools import capability_scope, tool_registry     # noqa: E402

RISKY_SNIPPET = "os.system('rm -rf ' + user_input)  # also eval(cached_expr)"


class _CapturingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def main() -> int:
    ok = True
    capture = _CapturingHandler()
    logging.getLogger("security.tool_scope").addHandler(capture)
    logging.getLogger("security.tool_scope").setLevel(logging.WARNING)

    # --- allowed call: security agent runs the static analyzer, gets real findings ---
    hits = capability_scope.call_tool(
        AgentType.SECURITY, "run_static_analysis",
        tool_registry.run_static_analysis, RISKY_SNIPPET,
    )
    print("[allowed] security -> run_static_analysis:", hits)
    allowed_ok = len(hits) >= 2  # os.system( and eval( should both fire
    print(f"  -> found the planted risky calls? {allowed_ok}")
    ok &= allowed_ok

    # --- out-of-scope call: docs agent is NOT permitted to run static analysis ---
    rejected = False
    try:
        capability_scope.call_tool(
            AgentType.DOCS, "run_static_analysis",
            tool_registry.run_static_analysis, RISKY_SNIPPET,
        )
    except ToolScopeError as exc:
        rejected = True
        print(f"\n[out-of-scope] docs -> run_static_analysis: rejected ({exc})")
    print(f"  -> rejected (not silently allowed)? {rejected}")
    ok &= rejected

    logged = any(
        getattr(r, "event", None) == "tool_scope_violation"
        and r.__dict__.get("agent_type") == "docs"
        and r.__dict__.get("tool_name") == "run_static_analysis"
        for r in capture.records
    )
    print(f"  -> logged as a security event (not silent)? {logged}")
    ok &= logged

    # --- unregistered tool name: rejected for EVERYONE, including the "right" agent ---
    unregistered_rejected = False
    try:
        capability_scope.enforce(AgentType.SECURITY, "delete_production_database")
    except ToolScopeError:
        unregistered_rejected = True
    print(f"\n[unregistered tool] rejected even for security agent? {unregistered_rejected}")
    ok &= unregistered_rejected

    # --- retrieve_context is open to all four agent types (no rejection) ---
    all_ok = all(
        tool_registry.is_allowed(a, "retrieve_context")
        for a in (AgentType.SECURITY, AgentType.QUALITY, AgentType.TESTS, AgentType.DOCS)
    )
    print(f"\n[shared tool] retrieve_context allowed for all 4 agent types? {all_ok}")
    ok &= all_ok

    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
