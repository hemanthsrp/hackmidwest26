# Financial Intelligence Multi-Agent System Architecture

## System Architecture Overview

This document outlines the architecture for an event-driven, decoupled multi-agent intelligence system designed for scraping, processing, analyzing, and storing financial data across multiple sources—including general news, social media, government/regulatory disclosures, and commodity feeds.

```
[ Extended Data Sources ]
  ├─ General News (Bloomberg, Reuters, CNBC, Seeking Alpha)
  ├─ Social Media (Reddit: r/wallstreetbets, r/stocks; X/Twitter)
  ├─ Congressional Trading (Senate eFD, House Clerk PTRs)
  ├─ SEC EDGAR (Forms 4, 8-K, 10-K, 10-Q)
  └─ Commodities & Ag (USDA WASDE, NOAA Weather, CME Futures)
       │
       ▼
[ Source Scraper Agents ]
       │
       ▼
[ Orchestration & Workflow Layer ]
  ├─ Tier 1: Deterministic Router (Kafka / RabbitMQ / Redis)
  ├─ Tier 2: Workflow Orchestrator (LangGraph / Temporal)
  └─ Tier 3: Strategic Synthesis Agent (LLM Master Agent)
       │
       ▼
[ Processing & Analysis Pipeline ]
  ├─ Deduplication & Event Clustering Agent
  ├─ NER & Entity Disambiguation Agent (Tickers, Sectors, Key Figures)
  ├─ Reporting Lag & Temporal Normalization Engine
  ├─ Cross-Source Anomaly & Squeeze Engine
  ├─ Credibility & Bias Analysis Agent
  └─ Financial Sentiment & Impact Scoring Agent
       │
       ▼
[ Hybrid Storage Layer & Audit ]
  ├─ PostgreSQL (Structured metadata, historical trades, audit logs)
  ├─ Vector Database (Embeddings for semantic search & RAG)
  └─ Immutable Raw Blob Store (S3 / GCS + LLM Trace Metadata)
```

---

## 1. Source-Specific Scraper Agents

### 1.1 General News Scraper Agent

- **Ingestion:** Leverages official RSS feeds, market news APIs (e.g., Financial Modeling Prep, MarketAux), and headless crawling libraries (`Playwright`, `Crawl4AI`).
- **Processing:** Extracts clean article content using `trafilatura` or `readability-lxml`, stripping advertisements, navigation, and boilerplate HTML prior to summarization.

### 1.2 Reddit Scraper Agent

- **Ingestion:** Connects via `PRAW` (Python Reddit API Wrapper) targeting financial subreddits (`r/wallstreetbets`, `r/stocks`, `r/options`, `r/investing`).
- **Filtering:** Removes noise by enforcing account age, karma, score velocity, and upvote ratio thresholds. Extracts stock tickers using regular expressions cross-referenced against master exchange symbol lists (NASDAQ/NYSE).

### 1.3 X / Twitter Scraper Agent

- **Ingestion:** Utilizes the official X API v2 or scrape endpoints constrained to a pre-curated whitelist of verified financial journalists, institutional analysts, and central banks.
- **Filtering:** Filters out bot spam, repetitive cashtag promoters (`$NVDA`, `$TSLA`), and unverified accounts based on historical accuracy ratings and engagement ratios.

### 1.4 Congressional Trading Scraper Agent

- **Ingestion:** Scrapes official portals—Senate eFD (Electronic Financial Disclosure) and House Clerk PTRs (Periodic Transaction Reports)—or ingests pre-cleansed disclosure APIs.
- **Parsing:** Parses HTML tables for Senate disclosures and employs PDF table extraction (`pdfplumber` or vision LLMs) for scanned House disclosure PDFs to produce normalized JSON records (Member Name, Chamber, Ticker, Transaction Type, Disclosed Amount Range, Trade Date, Filing Date).

### 1.5 SEC EDGAR & Executive Filings Agent

- **Ingestion:** Polls SEC RSS feeds and the SEC EFTS (EDGAR Full Text Search) API using required custom user-agent headers (`User-Agent: Sample Company Name AdminContact@domain.com`).
- **Target Filings & Extraction:**
  - **Form 4 (Insider Trading):** Parses XML directly for `reportingOwner`, executive role (`isOfficer`/`isDirector`), transaction type (`P` for open-market purchase, `S` for sale), shares remaining, and average execution price.
  - **Form 8-K (Material Corporate Events):** Extracts sections by item codes (e.g., _Item 1.01 Material Agreements_, _Item 2.02 Earnings_, _Item 5.02 Director/Officer Changes_).
  - **10-K / 10-Q (Periodic Reports):** Extracts _Item 1A (Risk Factors)_ and _Item 7 (MD&A)_, running automated text diffs against preceding filings to highlight dynamic risk shifts.

### 1.6 Commodities & Agricultural Data Agent

- **Ingestion:** Integrates specialized agency feeds and futures market APIs:
  - **USDA WASDE & Crop Reports:** Pulls monthly World Agricultural Supply and Demand Estimates and weekly Crop Progress reports via the USDA Open Data API.
  - **Geospatial & Climate Feeds:** Ingests NOAA Drought Monitor and precipitation data across major agricultural belts (e.g., US Midwest, Brazil Cerrado, Black Sea region).
  - **Futures Market Data:** Ingests CME/CBOT commodity futures price streams (CORN, SOYB, WEAT, LE) to track basis risk and spot-to-futures dynamics.
- **Metrics:** Tracks ending stocks-to-use ratios, crop yield estimates, soil moisture deficits, and export velocity.

---

## 2. Orchestration & Workflow Architecture

To minimize token costs, prevent queue saturation, and ensure fault tolerance, orchestration is decoupled across three tiers:

```
[ Raw Ingestion Payload ]
           │
           ▼
1. Deterministic Router (Kafka / RabbitMQ / Redis)
   └─ Zero-cost filtering (Regex, Karma/Score checks, Dup hashes)
           │
           ▼
2. Stateful Workflow Orchestrator (LangGraph / Temporal)
   └─ DAG state control, rate limits, conditional routing, retries
           │
           ▼
3. Strategic Synthesis Agent (LLM Master Agent)
   └─ High-level cross-source reasoning & portfolio-level alerting
```

### 2.1 Tier 1: Deterministic Message Router (Rule-Based)

- **Tech Stack:** Kafka, RabbitMQ, or Redis Pub/Sub.
- **Function:** Evaluates raw scraped payloads against fast computational rules prior to triggering LLM pipelines. Payload items failing baseline thresholds (e.g., Reddit posts with $<10$ upvotes or missing ticker regex matches) are discarded at zero LLM cost.

### 2.2 Tier 2: Stateful Workflow Orchestrator (DAG Engine)

- **Tech Stack:** LangGraph, Temporal, or Celery.
- **Function:** Coordinates execution dependencies between specialized processing agents. Manages retry loops, rate limits, exponential backoffs, and conditional execution paths (e.g., routing an SEC Form 4 to immediate analysis while routing routine news through deduplication first).

### 2.3 Tier 3: Strategic Synthesis Agent (LLM Master Agent)

- **Tech Stack:** Autonomous Agent Framework (LangGraph / Custom Python loop).
- **Function:** Operates on demand or during scheduled synthesis runs to resolve multi-source contradictions, evaluate macro asset risks, and generate executive intelligence briefings.

---

## 3. Processing & Analysis Pipeline Agents

### 3.1 Deduplication & Clustering Agent

Groups articles or posts covering the same breaking news event within a rolling time window using MinHash/LSH or vector cosine similarity thresholds ($> 0.85$) to prevent redundant signal generation.

### 3.2 Entity & Sector Disambiguation Agent

Executes Named Entity Recognition (NER) to link mentions to standardized stock tickers, industry sectors (e.g., Semiconductors, Agribusiness, Commercial Banking), key executives, and macro factors (e.g., Federal Reserve rate policy, crop yields).

### 3.3 Reporting Lag & Temporal Normalization Engine

To avoid misinterpreting delayed disclosures as real-time market catalysts (such as STOCK Act filings), time is indexed along three distinct axes:

1. **Event Timestamp ($t_e$):** When the transaction or underlying event occurred.
2. **Filing Timestamp ($t_f$):** When the regulatory disclosure or article was published.
3. **Ingestion Timestamp ($t_i$):** When the system ingested and processed the record.

#### Effective Market Impact Decay Formula:

The actionable impact score $I_{\text{effective}}$ decays exponentially based on reporting lag $\Delta t = t_f - t_e$:

$$I_{\text{effective}} = I_{\text{raw}} \cdot e^{-\lambda \cdot (t_f - t_e)}$$

_Where $\lambda$ is the source decay constant ($\lambda_{\text{news}} \approx 2.0\text{ hr}^{-1}$, whereas $\lambda_{\text{congressional}} \approx 0.05\text{ day}^{-1}$). Trades disclosed near the 45-day STOCK Act limit are classified as `Historical Position Adjustments` rather than immediate trade signals.\_

### 3.4 Cross-Source Anomaly & Squeeze Engine

Calculates divergence between social volume momentum and verified institutional/filing activity to detect market distortions:

```
                      [ Social Volume Spike ]
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
    [ SEC / News Confirmed? ]       [ No Fundamental Support ]
                 │                               │
                 ▼                               ▼
     High-Conviction Momentum          Potential Squeeze /
         Event Signal                 Pump-and-Dump Risk
```

- **Social Sentiment Velocity ($V_{\text{social}}$):** Standard deviations of ticker mention frequency across Reddit and X over a rolling 4-hour window.
- **Fundamental Flow Index ($F_{\text{fund}}$):** Weighted aggregate of SEC Form 4 insider buying, Form 8-Ks, and verified news volume.
- **Divergence Signals:**
  - **High $V_{\text{social}}$ + Low $F_{\text{fund}}$:** Flagged as `Retail Squeeze / Sentiment Anomaly`.
  - **High $V_{\text{social}}$ + High $F_{\text{fund}}$:** Flagged as `High-Conviction Institutional Event`.
  - **Low $V_{\text{social}}$ + High SEC Form 4 Buying:** Flagged as `Stealth Insider Accumulation`.

### 3.5 Credibility & Impact Model

Calculates a composite credibility score $C$ by evaluating domain baseline authority ($S_{\text{domain}}$), author track record ($S_{\text{author}}$), and cross-source verification ($S_{\text{consensus}}$) minus sensationalism penalties ($P_{\text{noise}}$):

$$C = \min\left(1.0, \left( w_1 \cdot S_{\text{domain}} + w_2 \cdot S_{\text{author}} + w_3 \cdot S_{\text{consensus}} \right) - P_{\text{noise}}\right)$$

_Where $w_1 + w_2 + w_3 = 1.0$. Official government filings set $S_{\text{domain}} = 1.0$, whereas social media feeds start lower but gain weight as $S_{\text{consensus}}$ rises across independent, high-credibility channels.\_

---

## 4. Execution Frequency & Scheduling Strategy

To optimize compute costs and API rate limits, execution schedules are tailored to source velocity and market impact:

### 4.1 Source Ingestion Frequency Matrix

| Source / Agent                 | Recommended Schedule                 | Ingestion Protocol          | Operational Focus                                             |
| :----------------------------- | :----------------------------------- | :-------------------------- | :------------------------------------------------------------ |
| **X / Twitter & Reddit**       | Every 1–5 minutes                    | WebSockets / High-Freq Poll | Catching social volume spikes and squeeze velocity.           |
| **Breaking General News**      | Every 2–5 minutes                    | RSS / News API polling      | Catching breaking catalysts prior to full market reaction.    |
| **SEC EDGAR (Form 4 & 8-K)**   | Every 5–15 minutes (8 AM–6 PM EST)   | SEC RSS / EFTS API          | Real-time monitoring of insider buying and material filings.  |
| **SEC EDGAR (10-K / 10-Q)**    | Daily (Off-peak batch)               | SEC API                     | Deep MD&A extraction and quarter-over-quarter risk diffing.   |
| **Congressional Trades**       | 1–2x Daily (5 PM & 9 PM EST)         | Scraper / API               | Capturing late-afternoon disclosure filings.                  |
| **USDA WASDE & Crop Reports**  | Calendar Trigger (Monthly 12 PM EST) | Open API / Scraper          | Targeted polling aligned with published USDA release times.   |
| **NOAA Weather & CME Futures** | 1–2x Daily (00:00 & 12:00 UTC)       | API / Market Feeds          | Tracking agricultural climate shifts and price basis spreads. |

### 4.2 Analysis Execution Triggers

1. **Immediate Ingestion Trigger (Event-Driven):** Scrapers immediately push validated payloads to the message broker for NER and credibility scoring.
2. **Threshold-Driven Trigger (Anomaly Detection):** The Cross-Source Anomaly Engine fires dynamically when social volume exceeds a $2.5\sigma$ deviation or when a high-impact Form 8-K is ingested.
3. **Batch Synthesis Schedule:**
   - **Pre-Market Brief (7:30 AM EST):** Compiles overnight SEC filings, international news, and social volume spikes into a daily watchlist.
   - **Post-Market Brief (5:30 PM EST):** Aggregates daily insider trades, congressional PTR disclosures, and commodity updates into a unified daily digest.

### 4.3 Cost & Resource Optimization

- **Market-Hours Scaling:** Reduces SEC and news polling frequencies by 80% during off-market hours (weekends and 8:00 PM – 6:00 AM EST).
- **Two-Tier Model Execution:** Uses fast, low-cost models (e.g., `gpt-4o-mini` or `Claude 3.5 Haiku`) for routine entity extraction, reserving primary models (`gpt-4o` or `Claude 3.5 Sonnet`) strictly for 8-K risk analysis and multi-source cross-synthesis.

---

## 5. Storage Architecture & Data Schema

The system uses a hybrid storage model:

- **PostgreSQL:** Stores relational metadata, timelines, exact trade disclosures, ticker relationships, and numerical credibility scores.
- **Vector DB (Qdrant, Chroma, or pgvector):** Stores vector embeddings of generated summaries for Retrieval-Augmented Generation (RAG) and semantic similarity search.

### Unified Ingestion JSON Schema

```json
{
  "article_id": "uuid-v4-string",
  "source_type": "sec_filing | commodity_report | congressional_disclosure | social_media | general_news",
  "source_name": "SEC EDGAR / USDA WASDE / Senate eFD / r/wallstreetbets / Bloomberg",
  "author_or_filer": "Form 4: Tim Cook (CEO) / Sen. John Doe / Jane Smith",
  "timestamps": {
    "event_timestamp": "2026-09-15T14:30:00Z",
    "filing_timestamp": "2026-10-10T11:00:00Z",
    "ingestion_timestamp": "2026-10-10T11:02:15Z",
    "reporting_lag_days": 24.85
  },
  "url": "https://www.sec.gov/Archives/edgar/data/...",
  "raw_storage_uri": "s3://financial-audit-raw/2026/10/10/sec_form4_89123.json.gz",
  "entities": {
    "tickers": ["AAPL"],
    "commodities": [],
    "sectors": ["Technology", "Consumer Electronics"],
    "key_people": ["Tim Cook"]
  },
  "filing_details": {
    "form_type": "Form 4",
    "transaction_type": "Purchase",
    "total_value_usd": 1500000.0,
    "shares_transacted": 6500,
    "price_per_share": 230.76
  },
  "agri_commodity_metrics": {
    "crop_type": null,
    "ending_stocks_mbu": null,
    "drought_severity_index": null
  },
  "sentiment": {
    "direction": "Bullish",
    "score": 0.88,
    "effective_impact_score": 0.42
  },
  "anomaly_detection": {
    "social_volume_std_dev": 0.5,
    "fundamental_flow_score": 0.9,
    "flag": "Stealth Insider Accumulation"
  },
  "credibility_metadata": {
    "overall_score": 1.0,
    "source_reliability_weight": 1.0,
    "verified_filing": true
  },
  "llm_audit_trace": {
    "model": "gpt-4o",
    "prompt_version": "v3.2",
    "extracted_quotes": [
      "Open market purchase of 6,500 shares executed at average price of $230.76"
    ]
  }
}
```

---

## 6. Human-in-the-Loop Auditability & Data Lineage

1. **Immutable Raw Storage:** Unprocessed HTML, PDF filings, and API payloads are written directly to object storage (`s3://financial-audit-raw/YYYY/MM/DD/{source_id}.json.gz`) before LLM analysis.
2. **LLM Execution Tracing:** Every generated insight stores:
   - Prompt version and model identifier.
   - Direct text quote spans from source documents verifying LLM summaries.
   - Metric-level confidence scores for sentiment, entities, and market impact.
