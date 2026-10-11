# Volatility surface builder

This service brings Hemanth's option implied-volatility project into the Hack Midwest repository. It calculates Black–Scholes prices and Greeks, inverts option prices to implied volatility, fits or generates SVI-style slices, interpolates a strike/maturity surface, and renders 2D skew and 3D surface charts. Its output is an **options-risk diagnostic**. It does not predict the underlying stock price or decide buy/hold/sell.

The imported source is now the installable `vol_surface_builder` package in `src/`. The original research narrative, methodology, and release history are kept in [docs/](docs/). The exploratory notebook is in [notebooks/](notebooks/).

## Current integration

- `sample` mode produces reproducible SPY-like synthetic option data. It is labeled `sample` and supports only `SPY`; it does not impersonate current quotes for another ticker.
- `live` mode requests a ticker's option chain through `yfinance`, filters quotes, computes implied volatility, and returns an explicit error when data cannot be obtained.
- The standalone FastAPI endpoint provides grid data and unit-labeled statistics for a future stock-detail chart. It is **not yet consumed** by the Research API or a frontend. That wiring and the shared v0 contract remain a team checkpoint.
- The command-line program exports PNG, optional interactive HTML, and the normalized option-IV CSV. Generated output is ignored by Git.

## Local setup

From this directory, using Python 3.11 or newer:

```sh
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q
.venv/bin/python -m vol_surface_builder.cli --source sample --ticker SPY
.venv/bin/python -m uvicorn vol_surface_builder.api:app --port 8002
```

Install `".[dev,live]"` to enable live option-chain retrieval. On Windows, use `.venv\Scripts\python`. The CLI writes to `output/` unless `--output-dir` is supplied. Use `--no-html` to skip the interactive charts.

## HTTP interface

`GET /health` reports local service readiness.

`POST /v0/volatility-surfaces` accepts:

```json
{"symbol": "SPY", "mode": "sample", "spot": 602.0}
```

The response contains `symbol`, `data_mode`, `source`, `retrieved_at`, `market_observed_at`, `spot`, `pricing_assumptions`, `statistics`, and `surface`. The surface has strike and maturity axes and a 2D implied-volatility grid. IV and the approximate skew statistic use **decimal volatility units** (for example, `0.20` means 20% annualized volatility). Maturities use years. `market_observed_at` is `null` because the source pipeline does not establish a reliable quote timestamp; the request's retrieval time is not a quote time. The imported pipeline uses fixed risk-free-rate and dividend-yield assumptions, currently 0.043 and 0.013; these must be reviewed for a live ticker before interpreting its IV.

Sample mode accepts only `SPY`. Live mode accepts ticker-shaped symbols; a provider failure returns `503 options_provider_unavailable` without switching to sample data. This route is a local service contract and does not change the proposed `/v0/research-assessments` response.

## Provenance and limits

The source checkout was `/Users/hemanthsrp/Downloads/vol-surface-builder-main` at commit `4612f97` when imported on 2026-10-10. The Black–Scholes, feed, interpolation, SVI, visualization, original tests, notebook, and Markdown methodology were carried over. Its old `setup.py` and `requirements.txt` are replaced by this service's `pyproject.toml`. Large generated charts and CSV output remain reproducible through the CLI.

The synthetic generator is a reduced-form, SVI-inspired illustration. Neither it nor the interpolated grid establishes an arbitrage-free surface, a current market forecast, or a validated assessment signal. The source README referred to an MIT license, but no license file was present in the provided checkout; confirm provenance before redistributing this service separately.

See [methodology](docs/methodology.md), [source project README archive](docs/original-project-readme.md), and [source changelog](docs/CHANGELOG.md) for the transferred research documentation.
