"""Wording check for the article questions: run a hand-labelled quiz through Jev and compare.

    python -m jev_tool.evals [--quiz PATH] [--out report.json]

This is a sanity check on a handful of samples. It can show that a question is badly
worded; it cannot support an accuracy claim.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from . import presets
from .core import JevTool, default_tool

DEFAULT_QUIZ = Path(__file__).resolve().parents[2] / "evals" / "article_quiz.json"
RELEVANCE_THRESHOLD = 0.5
MATERIALITY_MAX = len(presets.MATERIALITY_LEVELS) - 1


def load_quiz(path: Path | str = DEFAULT_QUIZ) -> dict[str, Any]:
    """Load and validate a quiz file. Raises ValueError naming the first bad record."""
    quiz = json.loads(Path(path).read_text(encoding="utf-8"))
    companies = quiz["companies"]
    seen: set[str] = set()
    for item in quiz["items"]:
        evidence, expected = item["evidence"], item["expected"]
        item_id = evidence["id"]
        if item_id in seen:
            raise ValueError(f"duplicate id: {item_id}")
        seen.add(item_id)
        if evidence["symbol"] not in companies:
            raise ValueError(f"{item_id}: no company name for symbol {evidence['symbol']}")
        if evidence.get("data_mode") != "sample":
            raise ValueError(f"{item_id}: quiz items must be data_mode 'sample'")
        if not evidence.get("title") or not evidence.get("summary"):
            raise ValueError(f"{item_id}: title and summary are required")
        if not isinstance(expected["relevant"], bool):
            raise ValueError(f"{item_id}: expected.relevant must be true or false")
        if not _accepted(expected["content_type"]) <= set(presets.CONTENT_TYPE_OPTIONS):
            raise ValueError(f"{item_id}: bad expected.content_type {expected['content_type']!r}")
        event_type = expected.get("event_type")
        if event_type is not None and not _accepted(event_type) <= set(presets.EVENT_TYPE_OPTIONS):
            raise ValueError(f"{item_id}: bad expected.event_type {event_type!r}")
        if expected.get("upcoming_event") not in (True, False, None):
            raise ValueError(f"{item_id}: expected.upcoming_event must be true, false or null")
        if expected["relevant"]:
            if not _accepted(expected["direction"]) <= set(presets.DIRECTION_OPTIONS):
                raise ValueError(f"{item_id}: bad expected.direction {expected['direction']!r}")
            if not _accepted(expected["materiality"]) <= set(range(MATERIALITY_MAX + 1)):
                raise ValueError(f"{item_id}: bad expected.materiality {expected['materiality']!r}")
        elif expected["direction"] is not None or expected["materiality"] is not None:
            raise ValueError(f"{item_id}: direction and materiality must be null when not relevant")
    return quiz


def _accepted(value: Any) -> set:
    """The answer key may list more than one acceptable answer for a judgment call."""
    return set(value) if isinstance(value, list) else {value}


def _label(value: Any) -> str:
    return "/".join(map(str, value)) if isinstance(value, list) else str(value)


def score_item(
    expected: dict[str, Any],
    answers: dict[str, dict[str, Any]],
    reversed_direction: str | None = None,
) -> dict[str, Any]:
    """Compare one item's answers with its key. Direction and materiality are only
    scored for items that are expected to be about the company; event type and
    upcoming event only where the key gives a value."""
    relevant_probability = answers["relevant"]["noul"]
    row: dict[str, Any] = {
        "relevant_probability": relevant_probability,
        "relevant_correct": (relevant_probability >= RELEVANCE_THRESHOLD) == expected["relevant"],
        "direction": answers["direction"]["choice"],
        "direction_confidence": answers["direction"]["confidence"],
        "content_type": answers["content_type"]["choice"],
        "content_type_correct": answers["content_type"]["choice"] in _accepted(expected["content_type"]),
        "event_type": answers["event_type"]["choice"],
        "event_type_correct": None,
        "upcoming_event_probability": answers["upcoming_event"]["noul"],
        "upcoming_event_correct": None,
        "materiality_score": answers["materiality"]["score"],
        "direction_correct": None,
        "materiality_exact": None,
        "materiality_within_one": None,
        "direction_flipped": None,
    }
    if expected.get("event_type") is not None:
        row["event_type_correct"] = row["event_type"] in _accepted(expected["event_type"])
    if expected.get("upcoming_event") is not None:
        row["upcoming_event_correct"] = (
            row["upcoming_event_probability"] >= RELEVANCE_THRESHOLD
        ) == expected["upcoming_event"]
    if reversed_direction is not None:
        row["direction_flipped"] = reversed_direction != row["direction"]
    if expected["relevant"]:
        level = round(row["materiality_score"])
        row["direction_correct"] = row["direction"] in _accepted(expected["direction"])
        accepted_levels = _accepted(expected["materiality"])
        row["materiality_exact"] = level in accepted_levels
        row["materiality_within_one"] = any(abs(level - a) <= 1 for a in accepted_levels)
    return row


def _rate(values: list[bool | None]) -> float | None:
    known = [v for v in values if v is not None]
    return sum(known) / len(known) if known else None


def _mean(values: list[float | None]) -> float | None:
    known = [v for v in values if v is not None]
    return mean(known) if known else None


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [r for r in rows if r["direction_correct"] is not None]
    return {
        "items": len(rows),
        "items_about_company": len(scored),
        "relevance_accuracy": _rate([r["relevant_correct"] for r in rows]),
        "direction_accuracy": _rate([r["direction_correct"] for r in rows]),
        "content_type_accuracy": _rate([r["content_type_correct"] for r in rows]),
        "event_type_accuracy": _rate([r["event_type_correct"] for r in rows]),
        "upcoming_event_accuracy": _rate([r["upcoming_event_correct"] for r in rows]),
        "materiality_exact": _rate([r["materiality_exact"] for r in rows]),
        "materiality_within_one": _rate([r["materiality_within_one"] for r in rows]),
        "direction_confidence_when_right": _mean(
            [r["direction_confidence"] for r in scored if r["direction_correct"]]
        ),
        "direction_confidence_when_wrong": _mean(
            [r["direction_confidence"] for r in scored if not r["direction_correct"]]
        ),
        "direction_flip_rate_when_options_reversed": _rate([r["direction_flipped"] for r in rows]),
        "direction_confusion": dict(
            Counter(f"{_label(r['expected']['direction'])} -> {r['direction']}" for r in scored if "expected" in r)
        ),
        "mean_input_tokens": _mean([r.get("input_tokens") for r in rows]),
        "mean_latency_ms": _mean([r.get("latency_ms") for r in rows]),
    }


def run_quiz(tool: JevTool, quiz: dict[str, Any]) -> dict[str, Any]:
    """Ask Jev every quiz item twice (normal and reversed direction options) and score it."""
    reversed_order = list(reversed(presets.DIRECTION_OPTIONS))
    rows: list[dict[str, Any]] = []
    model = None
    for item in quiz["items"]:
        evidence, expected = item["evidence"], item["expected"]
        state = presets.article_state(
            evidence["symbol"], quiz["companies"][evidence["symbol"]], evidence["title"], evidence["summary"]
        )
        started = time.perf_counter()
        first = tool.evaluate(state, presets.article_questions())
        latency_ms = (time.perf_counter() - started) * 1000
        if first.engine != "jev":
            return {"engine": "unavailable", "error": first.error, "failed_on": evidence["id"]}
        second = tool.evaluate(state, presets.article_questions(direction_order=reversed_order))
        reversed_direction = second.answers["direction"]["choice"] if second.engine == "jev" else None
        model = first.model
        rows.append(
            {
                "id": evidence["id"],
                "title": evidence["title"],
                "expected": expected,
                **score_item(expected, first.answers, reversed_direction),
                "input_tokens": first.input_tokens,
                "latency_ms": latency_ms,
                "request_id": first.request_id,
            }
        )
    return {
        "engine": "jev",
        "model": model,
        "question_set_version": presets.ARTICLE_QUESTION_SET_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": f"Sanity check on {len(rows)} hand-labelled samples. Not an accuracy claim.",
        "summary": summarize(rows),
        "rows": rows,
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}" if isinstance(value, float) else str(value)


def format_report(report: dict[str, Any]) -> str:
    lines = [
        f"Model {report['model']} | questions {report['question_set_version']} | {report['generated_at']}",
        report["note"],
        "",
    ]
    lines += [f"  {name:<44} {_fmt(value)}" for name, value in report["summary"].items()]
    misses = [
        r
        for r in report["rows"]
        if not r["relevant_correct"]
        or not r["content_type_correct"]
        or r["direction_correct"] is False
        or r["event_type_correct"] is False
        or r["upcoming_event_correct"] is False
        or r["materiality_exact"] is False
    ]
    lines += ["", f"Misses ({len(misses)}):"]
    for r in misses:
        lines.append(
            f"  {r['id']}: expected {r['expected']} | got relevant={r['relevant_probability']:.2f} "
            f"direction={r['direction']} content_type={r['content_type']} "
            f"event_type={r['event_type']} upcoming={r['upcoming_event_probability']:.2f} "
            f"materiality={r['materiality_score']:.2f}"
        )
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
