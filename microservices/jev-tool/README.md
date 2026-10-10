# jev-tool

Shared tool for quick, cheap decisions using Jev (TypeSafe AI's System One model). One codebase, two ways in:

- **Python functions** for pipeline code.
- **An MCP server over stdio** for Strands agents.

Background, limits and the list of where Jev should and should not be used: [docs/jev-integration-research.md](../../docs/jev-integration-research.md).

> **Status:** built and tested offline against a mock HTTP transport, and through a real stdio MCP round trip. **No call to the real TypeSafe API has been made yet** (no key). Question wording in `presets.py` is an untuned first draft.

## Setup

Python 3.10 or newer.

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"    # Windows; use .venv/bin/python elsewhere
.venv/Scripts/python -m pytest
```

Another service installs it with `pip install -e ../jev-tool`.

## Configuration

Environment variables (see `.env.example`; this package does not load `.env` files itself):

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
    judgment.relevant, judgment.direction, judgment.materiality

jev.judge_articles([{"symbol": ..., "company": ..., "title": ..., "summary": ...}, ...])
```

`jev.evaluate(state, questions)` sends several questions in one request, using the API's own question shape.

## MCP use from Strands

Tools: `jev_check`, `jev_classify`, `jev_score`, `jev_evaluate`, `judge_article`.

The stdio client does **not** pass the parent's environment to the server, so pass what it needs explicitly:

```python
import os, sys
from mcp.client.stdio import StdioServerParameters, stdio_client
from strands.tools.mcp import MCPClient

params = StdioServerParameters(
    command=sys.executable,
    args=["-m", "jev_tool.server"],
    env={
        "PATH": os.environ["PATH"],
        "JEV_ENABLED": "true",
        "TYPESAFE_API_KEY": os.environ["TYPESAFE_API_KEY"],
    },
)
client = MCPClient(lambda: stdio_client(params))

with client:
    tools = client.list_tools_sync()                 # give these to Agent(tools=tools)
    result = client.call_tool_sync("id-1", "jev_check", {"text": "...", "statement": "..."})
    result["structuredContent"]["probability"]
```

Listing and calling tools this way is exercised by `tests/test_mcp_server.py`. Handing the tools to an `Agent` has not been run here, because that needs a text model.

## First real call

Once you have a key:

```sh
export TYPESAFE_API_KEY=...   # do not commit
export JEV_ENABLED=true
.venv/Scripts/python -m pytest -m live -q
```

Record the model, request id, latency and `input_tokens` from the log line; that is the observed call the project docs ask for.

## Checking the question wording

`evals/article_quiz.json` holds 19 hand-labelled **sample** headlines for AAPL, NVDA and TSLA (written for testing, not real news) in the evidence shape proposed in `docs/api-contract-v0.md`. The harness runs each through the `judge_article` questions, then again with the direction options reversed, and compares with the answer key:

```sh
.venv/Scripts/python -m jev_tool.evals --out report.json
```

It reports relevance, direction and materiality agreement, confidence when right vs wrong, how often the answer flips when options are reordered, and tokens and latency per article. With Jev off it scores nothing and exits with code 2. It is a sanity check for the wording, not an accuracy measurement. The answer key is a first pass and worth a skim before trusting the numbers.

## Don't use Jev for

Arithmetic or comparing numbers, ordering dates, writing text, or being the only thing that decides buy / hold / sell. Details are in the research doc.
