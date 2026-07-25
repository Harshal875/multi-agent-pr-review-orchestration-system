"""LLM-as-judge that scores a pipeline run's findings against golden_dataset.py's
hand-labeled expectations. Two scoring modes, matching the two case shapes:

  - A normal case has expected findings: the judge decides, per expected issue, whether
    ANY actual finding substantively catches it (semantic match, not exact wording - the
    model's phrasing varies run to run even when it's genuinely right). Score is recall
    over the expected list, penalized for hallucinated severe findings.
  - An expect_clean case has none: score is purely "did the pipeline stay quiet" - 1.0 if
    no CRITICAL/HIGH finding appeared, 0.0 if it hallucinated one. No LLM call needed;
    this check is a plain severity scan."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from backend.evaluation.golden_dataset import ExpectedFinding, GoldenCase
from backend.tools.llm_client import complete_async

logger = logging.getLogger("evaluation.judge")

_JUDGE_MODEL = "openai/gpt-oss-120b"

_JUDGE_SYSTEM = """You are grading a code-review AI's output against a hand-labeled
golden answer key. You will be given a diff, a list of EXPECTED issues a correct
reviewer should catch, and the ACTUAL findings the AI under test produced.

For each expected issue, decide if ANY actual finding substantively catches it - the
same underlying problem, roughly the right file, at least the stated minimum severity.
Wording does not need to match; the underlying issue does. Also count any actual
CRITICAL or HIGH severity finding that does not correspond to a real problem in the diff
(a hallucination).

Respond with ONLY a JSON object, no prose, no markdown fences:
{"matched": [true, false, ...], "hallucinated_severe": 0, "notes": "one sentence"}
"matched" has exactly one entry per expected issue, in the order given."""


@dataclass
class CaseScore:
    case_id: str
    score: float  # 0.0-1.0
    matched: list[bool]
    hallucinated_severe: int
    notes: str


def _format_expected(expected: list[ExpectedFinding]) -> str:
    return "\n".join(
        f"{i + 1}. [{e.agent_type}, min severity {e.min_severity}] {e.description} "
        f"(expected in a file matching '{e.file_path_hint}')"
        for i, e in enumerate(expected)
    )


def _format_actual(findings: list[dict]) -> str:
    if not findings:
        return "(no findings produced)"
    return "\n".join(
        f"- [{f['severity']}] {f['agent_type']}/{f['category']} {f['file_path']}: "
        f"{f['summary']} — {f['rationale'][:200]}"
        for f in findings
    )


def _score_clean_case(case: GoldenCase, actual_findings: list[dict]) -> CaseScore:
    severe = [f for f in actual_findings if f["severity"] in ("CRITICAL", "HIGH")]
    return CaseScore(
        case_id=case.case_id,
        score=1.0 if not severe else 0.0,
        matched=[],
        hallucinated_severe=len(severe),
        notes=(
            f"{len(severe)} severe finding(s) on a diff expected to be clean"
            if severe else "no severe findings, as expected"
        ),
    )


_JUDGE_PARSE_ATTEMPTS = 3  # complete_async already retries network/rate-limit errors;
# this retries a *successful* call that came back empty or unparseable - live models
# occasionally return a truncated or garbled response with no exception raised, and a
# judge that fails closed on that noise (rather than trying again) corrupts the
# regression signal it exists to produce.


async def score_case(case: GoldenCase, actual_findings: list[dict]) -> CaseScore:
    if case.expect_clean:
        return _score_clean_case(case, actual_findings)

    user = (
        f"Diff:\n{case.diff}\n\n"
        f"Expected issues:\n{_format_expected(case.expected)}\n\n"
        f"Actual findings:\n{_format_actual(actual_findings)}"
    )
    matched: list[bool] = [False] * len(case.expected)
    hallucinated = 0
    notes = ""
    last_exc: Exception | None = None

    for attempt in range(1, _JUDGE_PARSE_ATTEMPTS + 1):
        try:
            result = await complete_async(
                model=_JUDGE_MODEL, system=_JUDGE_SYSTEM, user=user, max_tokens=1024,
            )
            text = result.text.strip()
            start, end = text.find("{"), text.rfind("}")
            if start == -1 or end == -1:
                raise ValueError(f"no JSON object in judge output: {text[:200]!r}")
            verdict = json.loads(text[start : end + 1])
            raw_matched = [bool(m) for m in verdict.get("matched", [])]
            hallucinated = int(verdict.get("hallucinated_severe", 0))
            notes = str(verdict.get("notes", ""))
            # Defensive pad/truncate in case the judge returns the wrong-length list.
            matched = (raw_matched + [False] * len(case.expected))[: len(case.expected)]
            last_exc = None
            break
        except Exception as exc:  # noqa: BLE001 - retry a few times, then fail closed
            last_exc = exc
            logger.warning(
                "case=%s: judge call/parse attempt %d/%d failed: %s",
                case.case_id, attempt, _JUDGE_PARSE_ATTEMPTS, exc,
            )

    if last_exc is not None:
        notes = f"judge error after {_JUDGE_PARSE_ATTEMPTS} attempts: {last_exc}"

    recall = sum(matched) / len(case.expected) if case.expected else 1.0
    score = max(0.0, recall - 0.25 * hallucinated)

    return CaseScore(
        case_id=case.case_id, score=score, matched=matched,
        hallucinated_severe=hallucinated, notes=notes,
    )
