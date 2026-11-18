"""coverage.json is the one list of covered stocks. The scheduler and the frontend are
built separately and cannot read it, so their copies are checked against it here."""

import json
import re
from importlib import resources
from pathlib import Path

import pytest

from research_api import v1

REPO = Path(__file__).resolve().parents[3]
STOCKS = json.loads(resources.files("research_api").joinpath("coverage.json").read_text())["stocks"]
SYMBOLS = [s["symbol"] for s in STOCKS]
INDUSTRIES = {s["industry"] for s in STOCKS}


def repo_file(relative: str) -> str:
    path = REPO / relative
    if not path.exists():
        pytest.skip(f"{relative} is not in this checkout")
    return path.read_text()


def test_the_list_is_well_formed_and_is_what_v1_serves() -> None:
    assert len(SYMBOLS) == len(set(SYMBOLS))
    assert all(re.fullmatch("[A-Z]{1,5}", s) for s in SYMBOLS)
    assert all(s["name"] and re.fullmatch("[a-z]+", s["industry"]) for s in STOCKS)
    assert list(v1.UNIVERSE) == SYMBOLS


@pytest.mark.parametrize("relative", ["compose.base.yml"])  # shared by both stacks
def test_scheduler_default_matches_the_list(relative: str) -> None:
    default = re.search(r"SCHEDULER_SYMBOLS: \$\{SCHEDULER_SYMBOLS:-([A-Z,]+)\}", repo_file(relative))
    assert default and default.group(1) == ",".join(SYMBOLS), f"update SCHEDULER_SYMBOLS in {relative}"


def test_env_example_scheduler_symbols_match_the_list() -> None:
    line = re.search(r"^SCHEDULER_SYMBOLS=(.*)$", repo_file(".env.example"), re.M)
    assert line and line.group(1) == ",".join(SYMBOLS), "update SCHEDULER_SYMBOLS in .env.example"


def test_frontend_industries_match_the_list() -> None:
    block = re.search(r"export const industries = \[(.*?)\];", repo_file("frontend/src/lib/market.ts"), re.S)
    names = re.findall(r'"([^"]+)"', block.group(1)) if block else []
    # The industry pages link to /industries/<name lowercased>.
    assert {n.lower() for n in names} == INDUSTRIES, "update industries in frontend/src/lib/market.ts"


def test_frontend_trending_sections_are_covered_industries() -> None:
    sections = re.search(r"trending\?section=\$\{\((\{.*?\})", repo_file("frontend/src/components/pages.tsx"))
    values = set(re.findall(r':\s*"([a-z]+)"', sections.group(1))) if sections else set()
    assert values and values - {"all", "buy", "sell"} <= INDUSTRIES
