"""Runs the full pipeline against golden_dataset.GOLDEN_SET, scores each case via
judge.py, and fails (non-zero exit) if the aggregate score drops below the last
known-good baseline by more than _DROP_TOLERANCE. Baseline persists to
evaluation/baseline_score.json - a plain, git-trackable file, not a database table
(this is a CI-time gate, not runtime state). Wired into CI in Phase 18.

Cases run sequentially, not in parallel, even though each case's 4 specialists already
run concurrently internally - staying sequential across cases keeps this well clear of
Groq's free-tier rate limits (already tight under one case's 4-way fan-out alone)."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import uuid
from pathlib import Path
from typing import Any

BASELINE_PATH = Path(__file__).resolve().parent / "baseline_score.json"
_DROP_TOLERANCE = 0.10  # allow up to this much absolute score drop before failing


async def _run_case(engine: Any, case: Any) -> list[dict]:
    from backend.evaluation.golden_dataset import REPO

    review_id = str(uuid.uuid4())
    initial = {
        "review_id": review_id, "repo": REPO, "pr_number": 0,
        "commit_sha": f"golden-{case.case_id}", "diff": case.diff, "findings": [],
    }
    result = await engine.run(review_id, initial)
    return result.get("deduped_findings", [])


async def run_gate(verbose: bool = True) -> tuple[float, dict]:
    """Run every golden case through the real pipeline and score it. Returns
    (aggregate_score, per_case_detail)."""
    from backend.evaluation import judge
    from backend.evaluation.golden_dataset import GOLDEN_SET
    from backend.orchestrator.langgraph_engine import LangGraphEngine

    engine = LangGraphEngine()
    per_case: dict[str, dict] = {}
    scores: list[float] = []

    for case in GOLDEN_SET:
        findings = await _run_case(engine, case)
        case_score = await judge.score_case(case, findings)
        per_case[case.case_id] = {
            "score": case_score.score,
            "matched": case_score.matched,
            "hallucinated_severe": case_score.hallucinated_severe,
            "notes": case_score.notes,
            "findings_count": len(findings),
        }
        scores.append(case_score.score)
        if verbose:
            print(f"  {case.case_id:32} score={case_score.score:.2f}  ({case_score.notes})")

    aggregate = sum(scores) / len(scores) if scores else 0.0
    return aggregate, per_case


def _load_baseline() -> dict | None:
    if BASELINE_PATH.exists():
        return json.loads(BASELINE_PATH.read_text())
    return None


def _save_baseline(score: float, per_case: dict) -> None:
    BASELINE_PATH.write_text(
        json.dumps(
            {
                "score": score,
                "per_case": per_case,
                "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            },
            indent=2,
        )
    )


async def main() -> int:
    print("Running regression gate against the golden dataset...")
    aggregate, per_case = await run_gate()
    print(f"\naggregate score: {aggregate:.3f}")

    baseline = _load_baseline()
    if baseline is None:
        print("no baseline recorded yet - recording this run as the baseline.")
        _save_baseline(aggregate, per_case)
        return 0

    baseline_score = baseline["score"]
    drop = baseline_score - aggregate
    print(f"baseline score: {baseline_score:.3f} (recorded {baseline['recorded_at']})")
    print(f"drop: {drop:.3f}  (tolerance: {_DROP_TOLERANCE})")

    if drop > _DROP_TOLERANCE:
        print(
            f"\nREGRESSION DETECTED: score dropped by {drop:.3f}, exceeding tolerance "
            f"{_DROP_TOLERANCE}. FAILING."
        )
        return 1

    if aggregate > baseline_score:
        print("score improved - updating baseline.")
        _save_baseline(aggregate, per_case)

    print("\nOK: no regression.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
