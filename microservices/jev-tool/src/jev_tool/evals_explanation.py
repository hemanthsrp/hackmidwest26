"""Wording check for the explanation questions: hand-labelled explanations run through Jev.

    python -m jev_tool.evals_explanation [--quiz PATH] [--out report.json]

A sanity check on a handful of samples, not an accuracy claim.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import presets
from .core import JevTool, default_tool
from .evals import _mean, _rate

DEFAULT_QUIZ = Path(__file__).resolve().parents[2] / "evals" / "explanation_quiz.json"
THRESHOLD = 0.5


def load_quiz(path: Path | str = DEFAULT_QUIZ) -> dict[str, Any]:
    """Load and validate. `expected.claims` has one entry per sentence: true, false, or
    null for sentences that are not claims about the evidence (not scored)."""
    quiz = json.loads(Path(path).read_text(encoding="utf-8"))
    seen: set[str] = set()
    for case in quiz["cases"]:
        case_id = case["id"]
        if case_id in seen:
            raise ValueError(f"duplicate id: {case_id}")
        seen.add(case_id)
        if case["evidence_set"] not in quiz["evidence_sets"]:
            raise ValueError(f"{case_id}: unknown evidence_set {case['evidence_set']!r}")
        sentences = presets.split_sentences(case["explanation"])
        expected = case["expected"]
        if len(expected["claims"]) != len(sentences):
            raise ValueError(
                f"{case_id}: {len(sentences)} sentences but {len(expected['claims'])} expected.claims"
            )
        for name in ("personal_advice", "promises_outcome"):
            if expected[name] not in (True, False, None):
                raise ValueError(f"{case_id}: expected.{name} must be true, false or null")
    return quiz


def _correct(probability: float, expected: bool | None) -> bool | None:
    return None if expected is None else (probability >= THRESHOLD) == expected


def score_case(expected: dict[str, Any], check: Any) -> dict[str, Any]:
    claims = [
        {
            "text": claim.text,
            "supported_probability": claim.supported,
            "expected": want,
            "correct": _correct(claim.supported, want),
        }
        for claim, want in zip(check.claims, expected["claims"])
    ]
    return {
        "claims": claims,
        "personal_advice_probability": check.personal_advice,
        "personal_advice_correct": _correct(check.personal_advice, expected["personal_advice"]),
        "promises_outcome_probability": check.promises_outcome,
        "promises_outcome_correct": _correct(check.promises_outcome, expected["promises_outcome"]),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    claims = [c for r in rows for c in r["claims"] if c["expected"] is not None]
    return {
        "cases": len(rows),
        "claims_scored": len(claims),
        "claim_accuracy": _rate([c["correct"] for c in claims]),
        "unsupported_claims_caught": _rate([c["correct"] for c in claims if c["expected"] is False]),
        "supported_claims_passed": _rate([c["correct"] for c in claims if c["expected"] is True]),
        "personal_advice_accuracy": _rate([r["personal_advice_correct"] for r in rows]),
        "promises_outcome_accuracy": _rate([r["promises_outcome_correct"] for r in rows]),
        "mean_input_tokens": _mean([r.get("input_tokens") for r in rows]),
        "mean_latency_ms": _mean([r.get("latency_ms") for r in rows]),
    }


def run_quiz(tool: JevTool, quiz: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    model = None
    for case in quiz["cases"]:
        started = time.perf_counter()
        check = tool.check_explanation(case["explanation"], quiz["evidence_sets"][case["evidence_set"]])
        latency_ms = (time.perf_counter() - started) * 1000
        if check.engine != "jev":
            return {"engine": "unavailable", "error": check.error, "failed_on": case["id"]}
        model = check.model
        rows.append(
            {
                "id": case["id"],
                **score_case(case["expected"], check),
                "input_tokens": check.input_tokens,
                "latency_ms": latency_ms,
                "request_id": check.request_id,
            }
        )
    return {
        "engine": "jev",
        "model": model,
        "question_set_version": presets.EXPLANATION_QUESTION_SET_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": f"Sanity check on {len(rows)} hand-labelled explanations. Not an accuracy claim.",
        "summary": summarize(rows),
        "rows": rows,
    }


def format_report(report: dict[str, Any]) -> str:
    lines = [
        f"Model {report['model']} | questions {report['question_set_version']} | {report['generated_at']}",
        report["note"],
        "",
    ]
    for name, value in report["summary"].items():
        shown = "n/a" if value is None else f"{value:.2f}" if isinstance(value, float) else value
        lines.append(f"  {name:<32} {shown}")
    lines += ["", "Misses:"]
    for row in report["rows"]:
        for claim in row["claims"]:
            if claim["correct"] is False:
                lines.append(
                    f"  {row['id']}: claim expected supported={claim['expected']} "
                    f"got {claim['supported_probability']:.2f} | {claim['text']}"
                )
        for name in ("personal_advice", "promises_outcome"):
            if row[f"{name}_correct"] is False:
                lines.append(f"  {row['id']}: {name} got {row[f'{name}_probability']:.2f}, expected the opposite")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quiz", type=Path, default=DEFAULT_QUIZ)
    parser.add_argument("--out", type=Path, help="write the full report as JSON")
    args = parser.parse_args(argv)

    report = run_quiz(default_tool(), load_quiz(args.quiz))
    if report["engine"] != "jev":
        print(f"Jev did not answer, nothing was scored: {report['error']}", file=sys.stderr)
        return 2
    print(format_report(report))
    if args.out:
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"\nReport written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
