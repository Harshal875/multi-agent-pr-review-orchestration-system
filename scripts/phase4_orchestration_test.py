"""Phase 4 verification: parallel fan-out + checkpoint/resume across a simulated crash.

Modes (each a SEPARATE process so resume is proven via Redis, not in-memory state):
  parallel <thread>  - run the whole graph once; assert all 4 specialists ran and
                       overlapped in time (wall clock ~1s, not ~4s).
  run1 <thread>      - inject a crash at aggregate; the 4 specialists checkpoint first,
                       then the run raises. Prints the stalled state (next=aggregate).
  run2 <thread>      - resume the SAME thread with no input; assert ONLY aggregate runs
                       (build_context/specialists are NOT re-executed) and it completes.

Driver: scripts/phase4_run.sh runs run1 then run2 in two processes and greps PASS.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# System temp, never the repo, so verification never leaves stray files behind.
SCRATCH = Path(tempfile.gettempdir()) / "phase4_logs"
SCRATCH.mkdir(exist_ok=True, parents=True)


def _fresh(path: Path) -> Path:
    if path.exists():
        path.unlink()
    return path


async def do_parallel(thread: str) -> int:
    from backend.orchestrator.langgraph_engine import LangGraphEngine

    exec_log = _fresh(SCRATCH / f"{thread}-parallel.log")
    os.environ["EXEC_LOG"] = str(exec_log)
    os.environ.pop("FAIL_AT_AGGREGATE", None)

    engine = LangGraphEngine()
    initial = {"review_id": thread, "repo": "Harshal875/x", "pr_number": 1,
               "commit_sha": "abc", "diff": "", "context": [], "findings": []}

    t0 = time.time()
    result = await engine.run(thread, initial)
    wall = time.time() - t0

    lines = exec_log.read_text().splitlines()
    ran = [ln.split("\t")[0] for ln in lines]
    specialist_ts = [float(ln.split("\t")[1]) for ln in lines if ln.startswith("specialist:")]
    spread = max(specialist_ts) - min(specialist_ts) if specialist_ts else 99

    all_four = all(f"specialist:{s}" in ran for s in ("security", "quality", "tests", "docs"))
    # Parallel => all 4 start within a tiny window and total wall ~1s (not 4s).
    overlapped = spread < 0.5 and wall < 2.5

    print(f"[parallel] ran={ran}")
    print(f"[parallel] wall={wall:.2f}s specialist_start_spread={spread:.3f}s")
    print(f"[parallel] findings={len(result.get('findings', []))} decision={result.get('decision')}")
    ok = all_four and overlapped and len(result.get("findings", [])) == 4
    print("[parallel] RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


async def do_run1(thread: str) -> int:
    from backend.orchestrator.langgraph_engine import LangGraphEngine

    exec_log = _fresh(SCRATCH / f"{thread}-run1.log")
    os.environ["EXEC_LOG"] = str(exec_log)
    os.environ["FAIL_AT_AGGREGATE"] = "1"

    engine = LangGraphEngine()
    initial = {"review_id": thread, "repo": "Harshal875/x", "pr_number": 2,
               "commit_sha": "def", "diff": "", "context": [], "findings": []}

    crashed = False
    try:
        await engine.run(thread, initial)
    except Exception as e:  # noqa: BLE001
        crashed = True
        print(f"[run1] crashed as injected: {type(e).__name__}: {e}")

    state = await engine.get_state(thread)
    ran = [ln.split("\t")[0] for ln in exec_log.read_text().splitlines()]
    nxt = state["next"] if state else None
    checkpointed_findings = len(state["values"].get("findings", [])) if state else 0

    print(f"[run1] ran={ran}")
    print(f"[run1] checkpoint next={nxt} findings_in_checkpoint={checkpointed_findings}")
    ok = crashed and nxt == ["aggregate"] and checkpointed_findings == 4
    print("[run1] RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


async def do_run2(thread: str) -> int:
    from backend.orchestrator.langgraph_engine import LangGraphEngine

    exec_log = _fresh(SCRATCH / f"{thread}-run2.log")
    os.environ["EXEC_LOG"] = str(exec_log)
    os.environ.pop("FAIL_AT_AGGREGATE", None)

    engine = LangGraphEngine()
    result = await engine.resume(thread)

    ran = [ln.split("\t")[0] for ln in exec_log.read_text().splitlines()] if exec_log.exists() else []
    print(f"[run2] ran_this_process={ran}  (expect ONLY ['aggregate'])")
    print(f"[run2] decision={result.get('decision')} overall={result.get('overall_confidence')}")
    # Resume must run ONLY aggregate; build_context/specialists stay checkpointed.
    ok = ran == ["aggregate"] and result.get("decision") in ("post", "awaiting_human")
    print("[run2] RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def _patch_llm_for_determinism() -> None:
    """Phase 4 tests graph topology & checkpointing, not LLM reasoning (that's Phase 8's
    job - see scripts/phase8_agents_test.py). Stub the one real network call (Groq) so
    this regression test is fast, free, and deterministic regardless of live model
    availability. With diff="" every specialist's retrieval/tool calls short-circuit
    already (base_agent.py), so this is the only network call left to stub.

    Patched onto backend.agents.base_agent (where the name is *used*), not
    backend.tools.llm_client (where it's *defined*) - the standard rule for monkeypatching
    a `from module import name` import: the call site resolves the name from its own
    module globals, not the original module, so patching there is what other code paths
    (base_agent.run_specialist) actually see."""
    import backend.agents.base_agent as base_agent_module
    from backend.tools.llm_client import LLMResult

    def _fake_complete(*, model, system, user, max_tokens=4096, effort=None, thinking=False):
        return LLMResult(
            text=(
                '[{"category":"test","summary":"stub finding","file_path":"PLACEHOLDER",'
                '"line_start":null,"line_end":null,"suggestion":null,"confidence":0.8,'
                '"rationale":"Phase 4 regression test - LLM call stubbed for determinism.",'
                '"severity":"INFO"}]'
            ),
            model="stub-model", input_tokens=0, output_tokens=0,
        )

    base_agent_module.complete = _fake_complete


async def main() -> int:
    _patch_llm_for_determinism()
    mode = sys.argv[1]
    thread = sys.argv[2]
    if mode == "parallel":
        return await do_parallel(thread)
    if mode == "run1":
        return await do_run1(thread)
    if mode == "run2":
        return await do_run2(thread)
    print("unknown mode", mode)
    return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
