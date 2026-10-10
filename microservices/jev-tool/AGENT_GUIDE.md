# Jev: guide for coding agents

Read this before adding any Jev call to this repository. It tells you when to use Jev, how to call it, and the rules every caller follows. Everything you need to use the tool is on this page.

**Jev in one line:** a fast, cheap model that answers yes/no, pick-one and rating questions about text. It does not write text and cannot do maths.

**The only way to call Jev in this repo is the `jev_tool` package in this folder.** Do not import `typesafe_sdk` or call the TypeSafe API from any other service.

## 1. Should this be a Jev call?

| Use Jev when | Use code instead when | Use an LLM instead when |
|---|---|---|
| The input is text | The input is numbers or dates | The output must be written text |
| The answer is yes/no, one option from a fixed list, or a coarse rating | The answer is arithmetic, a comparison, a sort, or a date check | The task needs several reasoning steps or tool use |
| You would otherwise spend an LLM turn on a quick classification | A fixed rule gives the right answer | |

Never use Jev for:

- Arithmetic, comparing prices or percentages, ordering or differencing dates.
- Being the only thing that decides buy / hold / sell.
- Producing a number shown to users as a probability or prediction.
- Anything containing account data, holdings, credentials or secrets.
- The only defence against hostile or injected text.

Planned uses per service, with priorities, are in [docs/jev-integration-research.md §6](../../docs/jev-integration-research.md). Check there before inventing a new use.

## 2. Add it to your service

```sh
pip install -e ../jev-tool                 # from microservices/<your-service>
pip install -e "../jev-tool[strands]"      # if a Strands agent will call it
```

Python 3.10 or newer.

Settings come from environment variables. For local work, copy `.env.example` to `.env` **in this folder** (it is gitignored) and they are read automatically; values already set in the process environment win. Point `JEV_ENV_FILE` at a different file if needed.

| Variable | Default | Purpose |
|---|---|---|
| `TYPESAFE_API_KEY` | none | The Jev key. Never commit it, log it, or pass it to a frontend. |
| `JEV_ENABLED` | `false` | Jev is called only when this is `true` |
| `JEV_MODEL` | `jev-1.13.0` | Pinned model |
| `JEV_TIMEOUT_SECONDS` | `5` | Per HTTP operation |
| `JEV_MAX_RETRIES` | `2` | Retries with backoff |
| `JEV_MAX_CONCURRENCY` | `8` | Threads used by batch calls |

## 3. The five rules

1. **Check `engine` on every result.** `"jev"` means a real answer. `"unavailable"` means there is no answer: answer fields are `None` and `error` says why.
2. **Never fill in for a missing answer and call it Jev.** Pass `unavailable` on as a stated limitation. A fixture or rule-based stand-in is allowed only if it is deliberately selected and carries its own label.
3. **Send text, not numbers.** Compute in code first and pass named buckets such as `"trend": "down"` if a question needs them.
4. **Keep the input small.** One article or one message per call. Do not send a whole evidence set.
5. **Log `model`, `request_id` and `question_set_version`.** Do not log the key. Do not turn on `TYPESAFE_LOG_LEVEL=debug` in shared environments; it prints request bodies.

The tool does not raise on API failures, timeouts or a missing key. You do not need `try/except` around calls; you need the `engine` check.

## 4. Calling it from code

Use one shared tool per process:

```python
from jev_tool import default_tool

jev = default_tool()
```

### Judge articles (the main use)

```python
judgment = jev.judge_article("NVDA", "Nvidia", title="...", summary="...")
```

If you already hold evidence items in the v0 API contract shape (`id`, `symbol`, `title`, `summary`, ...), pass them as they are. The contract has no company name, so you supply it:

```python
judgment = jev.judge_evidence(evidence_item, "Nvidia")
judgments = jev.judge_evidence_items(evidence_items, {"NVDA": "Nvidia", "AAPL": "Apple"})  # concurrent, order kept
```

Fields on the result (an `ArticleJudgment`):

| Field | Meaning |
|---|---|
| `engine`, `error` | See rule 1 |
| `evidence_id` | The `id` you passed in (`judge_evidence` only) |
| `relevant` | 0 to 1: how likely the item is mainly about the company |
| `direction` | `negative`, `neutral`, `positive` or `mixed`: what it reports about the company's business |
| `direction_probabilities`, `direction_confidence` | Spread across the four options, and how peaked it is (0 to 1) |
| `content_type` | `company_announcement`, `news_report`, `opinion_or_analysis`, `social_media_post` or `other` |
| `content_type_probabilities`, `content_type_confidence` | As above |
| `materiality` | 0 to 2: 0 routine or promotional, 1 notable, 2 major. A weighted average, so it can be 1.4. |
| `materiality_confidence` | 0 to 1 |
| `model`, `request_id`, `question_set_version` | For logs and cache keys |

A complete caller:

```python
from jev_tool import default_tool

RELEVANCE_FLOOR = 0.5  # the value used in the wording check; not tuned


def judged_evidence(evidence_items, companies):
    judgments = default_tool().judge_evidence_items(evidence_items, companies)
    usable, unjudged = [], []
    for item, judgment in zip(evidence_items, judgments):
        if judgment.engine != "jev":
            unjudged.append({"id": item["id"], "reason": judgment.error})
        elif judgment.relevant >= RELEVANCE_FLOOR:
            usable.append({**item, "judgment": judgment.model_dump()})
    return usable, unjudged  # report `unjudged` to the caller; do not drop it silently
```

How to read a judgment:

- Weigh `direction` together with `content_type` and `materiality`. A company's own promotion or one social post is weaker evidence than independent reporting.
- Low `direction_confidence` means the answer is shaky. In testing, the only answers that changed when the options were reordered had confidence below 0.45. Treat low-confidence directions as unknown.
- Use `materiality` for ranking and thresholds, not as an exact quantity.
- None of these numbers is a chance that the stock moves. Never display them as one.

### One-off questions

```python
jev.check(text, "Is this message asking about a specific stock?").probability          # 0 to 1
jev.classify(text, "What is the user asking for?", {
    "stock_question": "Asks about a company or ticker.",
    "preference_update": "Changes a goal, horizon or risk preference.",
    "other": None,
}).choice
jev.score(text, "How urgent is this?", ["can wait", "this week", "today"]).score       # 0 to 2
```

- `check` returns `probability`. Optional `true_means=` and `false_means=` spell out the boundary.
- `classify` returns `choice`, `probabilities`, `confidence`. Up to 255 options; each maps to a one-line description or `None`.
- `score` returns `score`, `levels`, `probabilities`, `confidence`. Give 2 to 10 levels, lowest first.
- `jev.evaluate(state, questions)` sends several questions about one input in a single request, using the TypeSafe question shape. Use it when you need more than one answer about the same text.

Writing a good question:

- Ask about one property. Split "is it relevant and negative?" into two questions.
- Say exactly what counts. Put the boundary in the option descriptions.
- Avoid negations and "which of these is not".
- Ask what the text *says*, not what someone should *do* about it.

## 5. Calling it from a Strands agent

```python
from strands import Agent
from jev_tool.strands_mcp import mcp_client

with mcp_client() as jev:
    agent = Agent(tools=jev.list_tools_sync())   # plus your model and other tools
    ...
```

Tools exposed: `jev_check`, `jev_classify`, `jev_score`, `jev_evaluate`, `judge_article`. They take the same arguments as the functions above and return the same fields.

To call a tool yourself without the agent choosing:

```python
with mcp_client() as jev:
    result = jev.call_tool_sync("call-1", "judge_article",
                                {"symbol": "NVDA", "company": "Nvidia", "title": "...", "summary": "..."})
    judgment = result["structuredContent"]       # a dict; check judgment["engine"]
```

Notes:

- Always build the client with `mcp_client()`. The MCP stdio launcher starts the server with an almost empty environment, and this helper passes the Jev settings through. A hand-built client without them returns `unavailable`.
- `mcp_client({"JEV_ENABLED": "false"})` overrides a setting for that server.
- Listing and calling tools is tested. Passing them to an `Agent` with a real model has not been run in this repo yet.
- If every item must be judged the same way on every run, call the function from code (section 4) and give the agent the results. Let the agent call Jev itself only for optional, ad hoc checks.

## 6. Testing your code without the network

```python
from jev_tool import JevTool

JevTool(enabled=False)                     # every call returns engine="unavailable"
JevTool(enabled=True, client=fake_client)  # a TypeSafe client on a mock transport
```

`tests/test_core.py` has a `make_tool()` helper that builds the second kind and returns canned answers. Copy that pattern. Test both paths: a real answer, and `unavailable`.

Real calls: `python -m pytest -m live -q` in this folder makes one call through the MCP server. The default test run never touches the network.

## 7. Adding a new kind of question

For a one-off, use `check`, `classify` or `score` from your own service. No change to this package is needed.

Add to this package only when several callers need the same wording. Then:

1. **Wording** in `src/jev_tool/presets.py`: the options and a function that builds the question objects. Bump the version string whenever wording or options change.
2. **Method and result** in `src/jev_tool/core.py`: a result model extending `_Result`, and a method on `JevTool` that calls `self._call(state, questions)` and returns the model. Follow `judge_article`.
3. **Agent tool** in `src/jev_tool/server.py`, if agents need it: an `@mcp.tool()` function with a docstring an LLM can follow. Add its name to `EXPECTED_TOOLS` in `tests/test_mcp_server.py`.
4. **Tests** in `tests/test_core.py` against the mock transport.
5. **A wording check before anyone relies on it.** Hand-label 15 or more samples and compare Jev's answers with them. `src/jev_tool/evals.py` and `evals/article_quiz.json` do this for the article questions and are the pattern to copy; that runner is specific to articles, so a new question family needs its own sample file and scoring.
6. **Document it** in the README and add a row to this guide.

Coordinate with Jet before changing existing wording: other services cache and threshold against `question_set_version`.

## 8. What is known about how well it works

- Real calls take about half a second per article and cost well under a hundredth of a cent.
- On 27 hand-written samples (news, blog posts, social posts), relevance and direction agreed with the answer key every time; content type missed two press-release style samples; materiality was always within one level. The key was written by the same person who wrote the samples and was loosened after a first run, so this shows the questions are workable. It is not an accuracy figure and must not be quoted as one.
- One call out of roughly a hundred failed with a connection error and timed out. Callers saw `unavailable`. Expect this occasionally.
- Details and request ids: `evals/report-2026-10-10-article-v2.json` and the research doc §12.

## 9. Where things are

| Path | What |
|---|---|
| `src/jev_tool/core.py` | `JevTool`, result models, `default_tool()` |
| `src/jev_tool/presets.py` | Question wording and versions |
| `src/jev_tool/server.py` | MCP server |
| `src/jev_tool/strands_mcp.py` | `mcp_client()` |
| `src/jev_tool/env.py` | `.env` loading |
| `src/jev_tool/evals.py`, `evals/` | Wording check and saved reports |
| `README.md` | Setup and human-oriented notes |
| `../../docs/jev-integration-research.md` | Background, limits, planned uses, sources |
