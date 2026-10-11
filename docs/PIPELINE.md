# Pipelines and where AI is used

State as of 2026-10-11. GitHub renders the diagrams below. **Orange boxes are AI calls; everything else is plain code or math.** Dashed boxes are built but not connected to anything yet.

The rule that matters most: **the label (`buy` / `hold` / `sell`) and the 0 to 100 score are never produced by a model.** They come from a fixed rule (`combiner-v1`). Models write summaries, tags and explanations around that result.

## 1. End to end

```mermaid
flowchart TD
    classDef ai fill:#ffd9a8,stroke:#c2410c,color:#000
    classDef store fill:#dbeafe,stroke:#1d4ed8,color:#000
    classDef off fill:#f3f4f6,stroke:#9ca3af,stroke-dasharray: 5 5,color:#555

    subgraph A["A. Ingest (scraper-analysis, POST /ingest/run, run by hand)"]
        direction TB
        S1["Sources: SEC EDGAR + Form 4, Marketaux news,<br/>official RSS, Senate eFD, House Clerk"] --> S2["Normalize, dedupe, stable IDs,<br/>credibility score"]
        S2 --> S3["Keep only records not already stored"]
        S3 --> S4["Tag: entities, sentiment, summary metadata<br/>Bedrock: Haiku 4.5"]:::ai
        S3 -.-> S4b["Optional Jev judgment and grade<br/>TypeSafe Jev, off by default"]:::off
        S4 --> S5["Embed title + summary<br/>Akamai hackathon-embedding"]:::ai
        S5 --> DB[("Postgres + pgvector<br/>evidence, signals")]:::store
        S6["Price signals: Yahoo Finance via yfinance"] --> DB
    end

    subgraph B["B. Read-only views of stored data (scraper-analysis)"]
        direction TB
        DB --> B1["GET /evidence, GET /signals"]
        DB --> B2["GET /divergence<br/>rule-based: price vs insiders vs congress vs news"]
        DB --> B3["POST /briefing<br/>cited research briefing<br/>Strands agent on Bedrock: Sonnet 5"]:::ai
    end

    subgraph C["C. Assessment (research-api, POST /v0/research-assessments, mode live)"]
        direction TB
        DB --> C1["Load evidence + signals for the symbol<br/>freshness check, 45-day window"]
        C1 --> C2["Optional: judge news that has no stored Jev judgment<br/>Jev, off unless enabled"]:::off
        C2 --> C3["Legs: news, insider, price, congress<br/>direction per leg, rules only"]
        C3 --> C4["Combiner: weights + thresholds<br/>label + score 0 to 100, rules only"]
        VOL["Options math: volatility-surface-builder<br/>optional, via VOL_SURFACE_URL"] -.-> C4
        C4 --> C5["Explanation + answer to the user's question<br/>Strands agent on Akamai hackathon-chat"]:::ai
        C5 --> C6["Optional: Jev checks the explanation<br/>for advice or unsupported claims"]:::off
        C6 --> OUT["Response: label, score, evidence list with sources,<br/>signals, explanation, warnings, decision trace"]
    end

    subgraph D["D. Recommended stocks (research-api)"]
        direction TB
        D0["Curated 24 stocks per sector"] --> D1["Run C1 to C4 for each stock<br/>no model explanation"]
        DB --> D1
        D1 --> D2["Rank by score, unscored last<br/>GET /v0/industries/slug/recommended-stocks"]
    end

    subgraph E["Built, not connected"]
        direction TB
        E1["Yahoo Finance MCP server"]:::off
        E2["Agentic search (Exa)"]:::off
        E3["Frontend (frontend/)"]:::off
    end

    OUT --> E3
    D2 --> E3
```

## 2. Every AI touchpoint

| # | Step | Model and provider | Input | Output | Can change the label or score? | On by default |
|---|---|---|---|---|---|---|
| 1 | Tag each new record at ingest | Haiku 4.5, Bedrock (`BEDROCK_TAGGING_MODEL_ID`) | Title and summary | Entities, sentiment, summary metadata | **No.** Tags are stored and shown, but the news leg does not read them (it reads only Jev judgments, rows 3 and 5) | Yes (`tag=true`) |
| 2 | Embed each new record | `hackathon-embedding`, Akamai (1024 dimensions) | Title and summary | Vector in pgvector | No | Yes, if Akamai env is set |
| 3 | Jev judgment and grade at ingest | TypeSafe Jev (`JEV_ENABLED`) | News and social text | `details.jev`, `details.grade`, off-topic flags | Yes, indirectly: the news leg reads only these judgments | **No** |
| 4 | Research briefing | Sonnet 5, Bedrock, Strands agent with lookup tools (`BEDROCK_SYNTHESIS_MODEL_ID`) | Stored evidence and signals | Cited points, conflicts, data gaps, uncertainty | No. It never gives buy or sell | On request (`POST /briefing`) |
| 5 | Judge unjudged news at assessment time | TypeSafe Jev | Article title and summary | Direction and relevance | Yes, indirectly: this is the news leg's only input if no judgment was stored at ingest | **No** |
| 6 | Embed the user's question | `hackathon-embedding`, Akamai | The `query` text | Vector for semantic search of stored evidence | No. It only picks which records the explanation looks at first | Only if a `query` is sent |
| 7 | Write the explanation and answer | `hackathon-chat`, Akamai, Strands agent | Evidence, signals, the decision result | Explanation points with evidence IDs, answer | **No.** The label and score are fixed before this step | Yes in `live`; falls back to a template if inference is not configured |
| 8 | Review the explanation | TypeSafe Jev | The written explanation and its evidence | Flags advice or unsupported claims; a failed review replaces the text with a template | No | **No** |

Everything not in this table is deterministic: source fetching, dedupe, credibility, signals, divergence, the legs, the combiner, the score, the freshness check, ranking, and the options math.

## 3. What decides the label and score

```mermaid
flowchart LR
    classDef ai fill:#ffd9a8,stroke:#c2410c,color:#000
    N["News leg<br/>0.40"] --> C
    I["Insider leg (Form 4)<br/>0.30"] --> C
    P["Price leg<br/>0.20"] --> C
    G["Congress leg<br/>0.10"] --> C
    Q["Options math<br/>raises the bar for buy or sell,<br/>never sets direction"] -.-> C
    C["net direction -1 to 1<br/>weighted over usable legs"] --> L["label: buy / hold / sell<br/>needs net past threshold 0.25 (0.40 if raised)<br/>and one evidence leg agreeing"]
    C --> SC["score = 50 + 50 x net, 0 to 100<br/>hold scores are kept inside the hold band"]
    L --> X["Explanation writer<br/>reads the result, cannot change it"]:::ai
    SC --> X
```

- At least two legs must be usable, or the result is `insufficient_data` with no score.
- A price move alone can never carry a buy or sell: one evidence leg (news, insider or congress) has to point the same way, otherwise the label is held at `hold`.
- The weights and thresholds are hand-set, not fitted to data. The score is a position on that scale, not a probability.

## 4. Known gaps in the pipeline

- **The news leg is empty while Jev is off.** It uses only records with a Jev judgment, and the Bedrock tags are not read by the combiner. With `JEV_ENABLED` unset (today), no news is judged, so a symbol's result rests on insiders, price and congress alone. Symbols with fewer than two usable legs return `insufficient_data` (AAPL did, despite 34 stored rows). Turning Jev on, or feeding the tags into the news leg, is the main lever for more scored stocks.
- **Ingest is manual.** Nothing runs on a schedule (the scheduler is off), and `live` assessments never trigger ingestion. Stored evidence goes stale; the freshness window is set to 7 days for now.
- **Coverage.** As of this writing about 25 symbols have stored evidence, so most of each sector is unscored.
- **Optional Jev steps are off**, so rows 3, 5 and 8 above do not run today.
- **Bedrock access.** The 5.5 models are refused by the account, so tagging uses Haiku 4.5 and the briefing uses Sonnet 5. See `BEDROCK_MODELS_WORKING` in `scraper-analysis/src/scraper_analysis/config.py`.
- **Not connected:** the Yahoo Finance MCP server, agentic search (Exa) and the frontend call nothing in this pipeline yet.
- **Option math** needs `VOL_SURFACE_URL`; a live option chain has not been run through it end to end.
