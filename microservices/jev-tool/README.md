# jev-tool

Shared tool for quick, cheap decisions using Jev (TypeSafe AI's System One model). One codebase, two ways in:

- **Python functions** for pipeline code.
- **An MCP server over stdio** for Strands agents.

Background, limits and the list of where Jev should and should not be used: [docs/jev-integration-research.md](../../docs/jev-integration-research.md).

> **Status:** tested offline against a mock HTTP transport, and against the real TypeSafe API on 2026-10-10 (direct call, MCP round trip, and the wording quiz below). Question wording in `presets.py` has had one sanity pass on 27 samples; it is not tuned.

## Setup

Python 3.10 or newer.

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"    # Windows; use .venv/bin/python elsewhere
.venv/Scripts/python -m pytest
```

Another service installs it with `pip install -e ../jev-tool`.

## Configuration

Copy `.env.example` to `.env` in this folder and fill it in (`.env` is gitignored). `default_tool()`, the MCP server and the quiz runner read it automatically; variables already set in the shell win. Set `JEV_ENV_FILE` to use a file somewhere else. A `JevTool(...)` you construct yourself reads only the process environment unless you call `load_env()` first.

| Variable | Default | Purpose |
|---|---|---|
| `TYPESAFE_API_KEY` | none | Read by the TypeSafe SDK |
| `JEV_ENABLED` | `false` | Jev is only called when this is `true` |
| `JEV_MODEL` | `jev-1.13.0` | Pinned model |
| `JEV_TIMEOUT_SECONDS` | `5` | Per HTTP operation |
| `JEV_MAX_RETRIES` | `2` | SDK retries with backoff |
| `JEV_MAX_CONCURRENCY` | `8` | Threads used by `judge_articles` |

## What you get back

Every result has `engine`:

- `"jev"`: the answer came from the TypeSafe API. `model` and `request_id` are set.
- `"unavailable"`: Jev is off or the call failed. Answer fields are `None` and `error` says why.

The tool never raises on an API failure and never invents an answer. **Callers must check `engine`** and decide what to do without an answer (for example, treat the item as unjudged).

## Python use

```python
from jev_tool import default_tool

jev = default_tool()  # one shared client, configured from the environment

jev.check("I was charged twice.", "Is this about billing?").probability
jev.classify("...", "What is the tone?", {"calm": None, "angry": None}).choice
jev.score("...", "How urgent is this?", ["can wait", "this week", "today"]).score

judgment = jev.judge_article("ACME", "Acme Corp", title="...", summary="...")
if judgment.engine == "jev":
    judgment.relevant, judgment.direction, judgment.content_type, judgment.materiality

jev.judge_articles([{"symbol": ..., "company": ..., "title": ..., "summary": ...}, ...])
```

`jev.evaluate(state, questions)` sends several questions in one request, using the API's own question shape.

## MCP use from Strands

Tools: `jev_check`, `jev_classify`, `jev_score`, `jev_evaluate`, `judge_article`.

```python
from jev_tool.strands_mcp import mcp_client

with mcp_client() as jev:
    tools = jev.list_tools_sync()                    # give these to Agent(tools=tools)
    result = jev.call_tool_sync("id-1", "jev_check", {"text": "...", "statement": "..."})
    result["structuredContent"]["probability"]
```

`mcp_client()` starts `python -m jev_tool.server` over stdio and passes the Jev settings through. It exists because the stdio client starts the server with a near-empty environment; building the client by hand without passing `TYPESAFE_API_KEY` and `JEV_ENABLED` gives `engine: unavailable`. Pass `mcp_client({"JEV_ENABLED": "false"})` to override a value. Needs `strands-agents` (`pip install -e "../jev-tool[strands]"`).

Listing and calling tools this way is exercised by `tests/test_mcp_server.py`. Handing the tools to an `Agent` has not been run here, because that needs a text model.

## Calling Jev from the backend

The backend should wrap this package in its own thin adapter and depend on that, not on `JevTool` directly. What the adapter can rely on:

| Need | Call | Notes |
|---|---|---|
| Judge one evidence item in the v0 contract shape | `default_tool().judge_evidence(evidence, company)` | Reads `symbol`, `title`, `summary`; echoes `id` back as `evidence_id`. The contract has no company name, so pass it. |
| Judge a list of them | `default_tool().judge_evidence_items(items, {"ACME": "Acme Corp"})` | Concurrent, order kept |
| One-off yes/no, pick-one, or rating | `check`, `classify`, `score` | |
| Same things from an agent | `mcp_client()` | Results under `structuredContent` |

Rules of the interface:

- **Check `engine` on every result.** `"jev"` means a real answer. `"unavailable"` means no answer was produced: answer fields are `None` and `error` says why. The tool never raises for an API failure and never substitutes an answer, so the adapter can pass `unavailable` straight through as a stated limitation.
- **Fixtures are the caller's business.** This package has no fixture mode. A deliberately selected fixture path belongs in the adapter and must carry its own label.
- **`model`, `request_id` and `question_set_version`** are on every Jev-backed result; log them. A change to question wording bumps `question_set_version`.
- **Result objects are pydantic models**; `.model_dump()` gives a plain dict.
- To test an adapter without the network, construct `JevTool(enabled=True, client=...)` with a TypeSafe client on a mock transport, as `tests/test_core.py` does, or `JevTool(enabled=False)` for the unavailable path.

## Live check

```sh
.venv/Scripts/python -m pytest -m live -q
```

Makes one real call through the MCP server, using the key from `.env`. The default test run leaves it out.

## Checking the question wording

`evals/article_quiz.json` holds 27 hand-labelled **samples** for AAPL, NVDA and TSLA: news items, blog posts, social posts and press-release style items (written for testing, not real content) in the evidence shape proposed in `docs/api-contract-v0.md`. The harness runs each through the `judge_article` questions, then again with the direction options reversed, and compares with the answer key:

```sh
.venv/Scripts/python -m jev_tool.evals --out report.json
```

Where a call is a matter of judgment, the answer key lists more than one accepted answer. It reports relevance, direction, content-type and materiality agreement, confidence when right vs wrong, how often the answer flips when options are reordered, and tokens and latency per article. With Jev off it scores nothing and exits with code 2. It is a sanity check for the wording, not an accuracy measurement. The answer key is hand-written and worth a skim before trusting the numbers.

Results from 2026-10-10 are saved in `evals/report-2026-10-10-article-v1.json` and `-v2.json` and summarised in the research doc (§12). Short version: relevance and direction agreed on every sample in the second run, content type missed the two press-release style samples, and the only answers that changed when options were reordered were the two lowest-confidence ones.

## Don't use Jev for

Arithmetic or comparing numbers, ordering dates, writing text, or being the only thing that decides buy / hold / sell. Details are in the research doc.
