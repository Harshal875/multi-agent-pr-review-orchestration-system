"""Docker-based isolated execution for any agent that needs to *run* PR code, rather
than only reason over diff text (Phase 7 - optional depth, per ROADMAP).

None of the Phase 8 specialist agents execute PR code: they reason over the diff plus
retrieved context and call run_static_analysis (a regex lint, no execution). So sandboxed
execution is intentionally left unimplemented for this build - not silently skipped, but
explicit: calling it raises, rather than pretending to sandbox something that never runs.

If a future agent needs to execute untrusted code, implement it here and route every
call through capability_scope.call_tool() first, so it inherits the same scope
enforcement as every other tool."""

from __future__ import annotations


def run_in_sandbox(*args, **kwargs):
    raise NotImplementedError(
        "No specialist agent executes PR code in this build - sandboxed execution is "
        "intentionally unimplemented. Implement a Docker-based sandbox here if a future "
        "agent needs to run untrusted code, and route calls through "
        "capability_scope.call_tool() for scope enforcement."
    )
