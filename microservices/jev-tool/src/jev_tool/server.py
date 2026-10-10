"""MCP face of the shared Jev tool. Runs over stdio: `python -m jev_tool.server`."""

from __future__ import annotations

import logging
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer

from .core import (
    ArticleJudgment,
    CheckResult,
    ClassifyResult,
    EvaluateResult,
    ScoreResult,
    default_tool,
)

mcp = MCPServer(
    "jev-tool",
    instructions=(
        "Quick, cheap typed decisions about text using Jev. Use these instead of reasoning "
        "yourself when the answer is a yes/no, a pick from a fixed list, or a coarse rating. "
        "Do not use them for arithmetic, comparing numbers, or ordering dates. Every result "
        "has `engine`: if it is not 'jev', no answer was produced and `error` says why."
    ),
)


@mcp.tool()
def jev_check(
    text: str,
    statement: str,
    true_means: str | None = None,
    false_means: str | None = None,
) -> CheckResult:
    """Yes/no question about a piece of text.

    Returns `probability` (0 to 1) that `statement` is true of `text`. Ask about one
    property at a time. `true_means` / `false_means` optionally spell out the boundary.
    """
    return default_tool().check(text, statement, true_means, false_means)


@mcp.tool()
def jev_classify(text: str, instructions: str, options: dict[str, str | None]) -> ClassifyResult:
    """Pick exactly one option for a piece of text.

    `options` maps each option name to a one-line description (or null). Returns the
    chosen option, the probability of every option, and a 0 to 1 confidence.
    """
    return default_tool().classify(text, instructions, options)


@mcp.tool()
def jev_score(text: str, instructions: str, levels: list[str]) -> ScoreResult:
    """Rate a piece of text on a short ordered scale.

    `levels` lists 2 to 10 level descriptions from lowest to highest. `score` is a
    position on that scale counted from 0. Use it for ranking and thresholds, not as
    an exact quantity.
    """
    return default_tool().score(text, instructions, levels)


@mcp.tool()
def jev_evaluate(state: Any, questions: dict[str, dict[str, Any]]) -> EvaluateResult:
    """Several questions about one state in a single request (advanced).

    `questions` maps your own ids to objects with `type` ("noul", "choice" or "score"),
    `instructions`, and `criteria` (choice: option -> description; score: ordered list).
    Prefer jev_check, jev_classify or jev_score for a single question.
    """
    return default_tool().evaluate(state, questions)


@mcp.tool()
def judge_article(symbol: str, company: str, title: str, summary: str) -> ArticleJudgment:
    """Judge one news item for one company.

    Returns `relevant` (probability the article is mainly about the company),
    `direction` (negative / neutral / positive / mixed) with probabilities, and
    `materiality` (0 = routine or promotional, 1 = notable, 2 = major).
    """
    return default_tool().judge_article(symbol, company, title, summary)


def main() -> None:
    # stdout carries the MCP protocol on stdio, so logs must go to stderr.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    mcp.run()


if __name__ == "__main__":
    main()
