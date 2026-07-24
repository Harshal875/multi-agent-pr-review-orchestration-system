"""Tool catalog (Phase 7): declares which tools exist, which agent types may call each
one, and — for sync, in-process tools — the callable it dispatches to. This module only
declares and implements; capability_scope.py is the single checkpoint every call must
pass through before a tool actually runs.

Async tools (like retrieval) aren't dispatched through here — an agent calls
capability_scope.enforce() itself, then awaits the real async function directly, so this
registry never has to bridge sync/async."""

from __future__ import annotations

import re

from backend.models.enums import AgentType

# tool name -> which agent types may call it. An empty/missing entry means "nobody" -
# this is also how an unregistered tool name gets rejected (ROADMAP §Phase 7).
TOOL_SCOPES: dict[str, set[AgentType]] = {
    "retrieve_context": {
        AgentType.SECURITY, AgentType.QUALITY, AgentType.TESTS, AgentType.DOCS,
    },
    "run_static_analysis": {AgentType.SECURITY},
}

# A cheap first-pass lint for known-risky Python calls - not a full static analyzer,
# just a fast pattern check the security agent can run before/alongside LLM reasoning.
_RISKY_PATTERNS: dict[str, str] = {
    r"\beval\(": "eval() can execute arbitrary strings as code",
    r"\bexec\(": "exec() can execute arbitrary strings as code",
    r"pickle\.loads\(": "pickle.loads() can execute arbitrary code during deserialization",
    r"os\.system\(": "os.system() runs a shell command built from a string",
    r"shell\s*=\s*True": "shell=True is vulnerable to shell injection",
}


def run_static_analysis(diff_text: str) -> list[str]:
    """Regex lint over a diff/snippet for known-risky calls. Returns one line per hit."""
    return [
        why for pattern, why in _RISKY_PATTERNS.items() if re.search(pattern, diff_text)
    ]


def is_allowed(agent_type: AgentType, tool_name: str) -> bool:
    return agent_type in TOOL_SCOPES.get(tool_name, set())


def allowed_tools(agent_type: AgentType) -> set[str]:
    return {name for name, scopes in TOOL_SCOPES.items() if agent_type in scopes}
