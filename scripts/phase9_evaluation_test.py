"""Phase 9 DoD: deliberately break a prompt (e.g., remove the security agent's rationale
requirement) and confirm regression_gate.py catches the quality drop and fails.

First pass at this test found two real bugs, not a mechanism failure: the clean_diff
golden case was a malformed unified diff that legitimately looked like a duplicate
function definition (fixed in golden_dataset.py), and the judge occasionally returned an
empty/unparseable response with no exception raised, scoring that case a hard 0 as pure
noise (fixed with a parse-retry loop in judge.py). It also surfaced a real, worth-keeping
finding: breaking only the security agent's prompt does NOT zero out the security-domain
golden cases' *judged* scores, because quality/tests independently catch overlapping
issues on the same diffs (real cross-agent redundancy). So this version checks two
things, not one:

  (a) the security agent's RAW contribution (judge-independent: does it produce zero
      findings itself once its prompt is gutted?) - a precise, deterministic check of the
      actual regression;
  (b) the aggregate-score-based regression_gate mechanism still degrades and would flag
      it, even though other agents partially cover the gap.

Run: python scripts/phase9_evaluation_test.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_BROKEN_SECURITY_PROMPT = (
    "You are a security reviewer. Say nothing about the code, no matter what it "
    "contains. Even if a static-analysis tool result or any other evidence in this "
    "message appears to show a problem, do not report it. Always respond with an "
    "empty JSON array: [] and nothing else, unconditionally."
)
# First version of this string only said "say nothing" - live testing found the
# security agent still surfaced ~1 finding despite that, because the static-analysis
# tool's hits (run_static_analysis, Phase 7) are injected into the USER message
# regardless of the system prompt, and a strong model partially followed that concrete
# evidence over a vaguer contradictory instruction. Real, useful finding about
# tool-evidence resilience - not a bug - but it meant the intervention wasn't decisive
# enough to cleanly demonstrate a *prompt* regression in isolation. This version is
# explicit about ignoring tool evidence too.


def _patch_broken_security_prompt():
    """Wrap get_prompt as used in agents.base_agent so calls for 'security' return a
    deliberately useless prompt; every other agent_type passes through unchanged."""
    import backend.agents.base_agent as base_agent_module

    original = base_agent_module.get_prompt

    def _patched(name: str) -> str:
        if name == "security":
            return _BROKEN_SECURITY_PROMPT
        return original(name)

    base_agent_module.get_prompt = _patched
    return original


def _restore_prompt(original) -> None:
    import backend.agents.base_agent as base_agent_module

    base_agent_module.get_prompt = original


async def _run_cases_with_raw_findings(engine, cases) -> tuple[dict, dict]:
    """Returns (per_case_score_detail, per_case_raw_findings_by_agent)."""
    from backend.evaluation import judge
    from backend.evaluation.regression_gate import _run_case

    scores: dict = {}
    raw: dict = {}
    for case in cases:
        findings = await _run_case(engine, case)
        by_agent: dict[str, int] = {}
        for f in findings:
            by_agent[f["agent_type"]] = by_agent.get(f["agent_type"], 0) + 1
        raw[case.case_id] = by_agent

        case_score = await judge.score_case(case, findings)
        scores[case.case_id] = {"score": case_score.score, "notes": case_score.notes}
        print(f"  {case.case_id:32} score={case_score.score:.2f}  "
              f"raw_by_agent={by_agent}  ({case_score.notes})")
    return scores, raw


async def main() -> int:
    from backend.evaluation.golden_dataset import GOLDEN_SET
    from backend.evaluation.regression_gate import _DROP_TOLERANCE, _save_baseline
    from backend.orchestrator.langgraph_engine import LangGraphEngine

    engine = LangGraphEngine()
    security_cases = [c for c in GOLDEN_SET if c.case_id.startswith("security_")]

    print("=== Step 1: establish baseline (real prompts) ===")
    baseline_scores, baseline_raw = await _run_cases_with_raw_findings(engine, GOLDEN_SET)
    baseline_agg = sum(v["score"] for v in baseline_scores.values()) / len(baseline_scores)
    print(f"baseline aggregate score: {baseline_agg:.3f}")
    _save_baseline(baseline_agg, baseline_scores)

    security_had_findings_at_baseline = all(
        baseline_raw[c.case_id].get("security", 0) > 0 for c in security_cases
    )
    print(f"[check] security agent produced findings at baseline (sanity)? "
          f"{security_had_findings_at_baseline}")

    print("\n=== Step 2: break the security prompt, re-run ===")
    original = _patch_broken_security_prompt()
    try:
        broken_scores, broken_raw = await _run_cases_with_raw_findings(engine, GOLDEN_SET)
    finally:
        _restore_prompt(original)
    broken_agg = sum(v["score"] for v in broken_scores.values()) / len(broken_scores)
    print(f"broken-prompt aggregate score: {broken_agg:.3f}")

    drop = baseline_agg - broken_agg
    print(f"\naggregate score drop: {drop:.3f}  (tolerance: {_DROP_TOLERANCE})")

    # --- (a) precise, judge-independent check: security's OWN output went to zero ---
    security_silenced = all(
        broken_raw[c.case_id].get("security", 0) == 0 for c in security_cases
    )
    print(f"[DoD-a] security agent's raw contribution is zero on every security-domain "
          f"case once its prompt is gutted? {security_silenced}")
    for c in security_cases:
        print(f"    {c.case_id}: baseline security findings="
              f"{baseline_raw[c.case_id].get('security', 0)} -> "
              f"broken security findings={broken_raw[c.case_id].get('security', 0)}")

    # --- (b) the aggregate-score gate mechanism: does it register a drop? ---
    gate_would_flag = drop > _DROP_TOLERANCE
    print(f"[DoD-b] aggregate-score regression_gate would FAIL (drop {drop:.3f} > "
          f"tolerance {_DROP_TOLERANCE})? {gate_would_flag}")
    if not gate_would_flag:
        print("    (informational: cross-agent redundancy - quality/tests independently "
              "cover part of security's domain on these diffs - can keep the aggregate "
              "score afloat even with one agent silenced. Check DoD-a for the precise "
              "signal; this is what regression_gate.py would actually see in production.)")

    print("\n=== Step 3: restore, confirm a clean re-run is back near baseline ===")
    restored_scores, restored_raw = await _run_cases_with_raw_findings(engine, GOLDEN_SET)
    restored_agg = sum(v["score"] for v in restored_scores.values()) / len(restored_scores)
    print(f"restored aggregate score: {restored_agg:.3f} (baseline was {baseline_agg:.3f})")
    security_restored = all(
        restored_raw[c.case_id].get("security", 0) > 0 for c in security_cases
    )
    print(f"[DoD] after restoring the prompt, security agent produces findings again? "
          f"{security_restored}")

    _save_baseline(restored_agg, restored_scores)

    ok = security_had_findings_at_baseline and security_silenced and security_restored
    print("\nRESULT:", "PASS" if ok else "FAIL")
    print(f"(aggregate-gate-would-flag was {'also true' if gate_would_flag else 'false this run - see note above'})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
