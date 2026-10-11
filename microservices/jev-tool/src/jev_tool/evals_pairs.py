"""Wording check for the same-story question: hand-labelled pairs run through Jev.

    python -m jev_tool.evals_pairs [--quiz PATH] [--out report.json]

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
from .evals import _rate

DEFAULT_QUIZ = Path(__file__).resolve().parents[2] / "evals" / "same_story_quiz.json"
THRESHOLD = 0.5


def load_quiz(path: Path | str = DEFAULT_QUIZ) -> dict[str, Any]:
    """`pairs` reference `items` by key; `same` is true, false, or null (not scored)."""
    quiz = json.loads(Path(path).read_text(encoding="utf-8"))
    for pair in quiz["pairs"]:
        for key in (pair["a"], pair["b"]):
            if key not in quiz["items"]:
                raise ValueError(f"unknown item {key!r} in pair {pair}")
        if pair["same"] not in (True, False, None):
            raise ValueError(f"pair {pair['a']}/{pair['b']}: same must be true, false or null")
    return quiz


def run_quiz(tool: JevTool, quiz: dict[str, Any]) -> dict[str, Any]:
    keys = list(quiz["items"])
    items = [quiz["items"][key] for key in keys]
    index_pairs = [(keys.index(p["a"]), keys.index(p["b"])) for p in quiz["pairs"]]
    started = time.perf_counter()
    result = tool.same_story(items, index_pairs)
    latency_ms = (time.perf_counter() - started) * 1000
    if result.engine != "jev":
        return {"engine": "unavailable", "error": result.error}
    rows = []
    for pair, answer in zip(quiz["pairs"], result.pairs):
        correct = None if pair["same"] is None else (answer.same >= THRESHOLD) == pair["same"]
        rows.append({**pair, "same_probability": answer.same, "correct": correct})
    return {
        "engine": "jev",
        "model": result.model,
        "question_set_version": presets.SAME_STORY_QUESTION_SET_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": f"Sanity check on {len(rows)} hand-labelled pairs. Not an accuracy claim.",
        "summary": {
            "pairs": len(rows),
            "pairs_scored": sum(r["correct"] is not None for r in rows),
            "accuracy": _rate([r["correct"] for r in rows]),
            "same_story_found": _rate([r["correct"] for r in rows if r["same"] is True]),
            "different_story_kept_apart": _rate([r["correct"] for r in rows if r["same"] is False]),
            "input_tokens": result.input_tokens,
            "latency_ms": latency_ms,
        },
        "request_id": result.request_id,
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
        lines.append(f"  {name:<28} {shown}")
    lines += ["", "Pairs:"]
    for row in report["rows"]:
        mark = {True: "ok  ", False: "MISS", None: "    "}[row["correct"]]
        lines.append(f"  {mark} {row['a']} / {row['b']}: expected {row['same']}, got {row['same_probability']:.2f}")
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
