"""Commodities & agricultural signals (README 1.6), scoped to what needs no
paid or hard-to-obtain access. All three sources live-verified 2026-10-10:

- Futures price: yfinance continuous futures (ZC=F corn, ZS=F soybeans,
  ZW=F wheat). Free, no key.
- Precipitation: NOAA Climate Data Online v2, GSOM monthly totals (needs the
  free NOAA_CDO_TOKEN).
- Drought: US Drought Monitor statistics service. Free, no key.

Deliberately NOT covered (documented gap, not silently skipped): USDA
WASDE/ending stocks-to-use (FAS PSD), NASS crop progress/yield estimates,
export velocity, and soil moisture. The README lists those metrics; they
need USDA keys we chose not to chase for the hackathon demo. CME futures
come from Yahoo's continuous contracts, not a licensed CME feed, so treat
them as indicative.

Honest limits: precipitation is a raw monthly mean across stations -- it is
NOT adjusted against climatological normals and does not filter stations
with missing days, so it says "how wet", not "how anomalous". These are
historical/realized measures, never forecasts.

Symbols are the README's commodity tickers (CORN, SOYB, WEAT). Live cattle
(LE) is omitted: "LE" is also Lands' End's stock ticker, and mapping it to
cattle futures would answer a stock query with the wrong asset.
"""

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
import yfinance as yf

from ..config import get_settings
from ..models.signal import Signal
from .base import FetchResult, SourceUnavailableError, load_fixture, resolve

FIXTURE_FILE = "commodity_signals_sample.json"
NOAA_URL = "https://www.ncdc.noaa.gov/cdo-web/api/v2/data"
USDM_URL = "https://usdmdataservices.unl.edu/api/StateStatistics/GetDroughtSeverityStatisticsByAreaPercent"


@dataclass(frozen=True)
class Commodity:
    name: str
    futures_ticker: str
    state_fips: tuple[str, ...]  # primary growing states, for weather/drought


COMMODITIES: dict[str, Commodity] = {
    "CORN": Commodity("Corn", "ZC=F", ("19", "17", "31", "27", "18")),  # IA IL NE MN IN
    "SOYB": Commodity("Soybeans", "ZS=F", ("19", "17", "27", "18", "31")),
    "WEAT": Commodity("Wheat", "ZW=F", ("20", "38", "46")),  # KS ND SD
}


def is_commodity(symbol: str) -> bool:
    return symbol.upper() in COMMODITIES


def _futures_signal(symbol: str, c: Commodity) -> Signal:
    try:
        closes = yf.Ticker(c.futures_ticker).history(period="35d")["Close"].dropna()
    except Exception as exc:
        raise SourceUnavailableError(str(exc)) from exc
    if len(closes) < 2 or float(closes.iloc[0]) == 0:
        raise SourceUnavailableError(f"no usable futures history for {c.futures_ticker}")
    pct = (float(closes.iloc[-1]) - float(closes.iloc[0])) / float(closes.iloc[0]) * 100
    return Signal(
        symbol=symbol, name=f"{c.name} futures 30-day price change", value=round(pct, 4),
        unit="percent", window="30d",
        as_of=closes.index[-1].to_pydatetime().replace(tzinfo=timezone.utc),
        source=f"Yahoo Finance (yfinance) {c.futures_ticker}", data_mode="live",
    )


def _precipitation_signal(symbol: str, c: Commodity, token: str) -> Signal:
    today = datetime.now(timezone.utc)
    month_end = today.replace(day=1) - timedelta(days=1)
    month_start = month_end.replace(day=1)
    values: list[float] = []
    try:
        with httpx.Client(headers={"token": token}, timeout=60.0) as client:
            for fips in c.state_fips:
                resp = client.get(NOAA_URL, params={
                    "datasetid": "GSOM", "datatypeid": "PRCP", "locationid": f"FIPS:{fips}",
                    "startdate": month_start.date().isoformat(), "enddate": month_end.date().isoformat(),
                    "units": "metric", "limit": 1000,
                })
                resp.raise_for_status()
                values += [r["value"] for r in resp.json().get("results", []) if r.get("value") is not None]
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise SourceUnavailableError(str(exc)) from exc
    if not values:
        raise SourceUnavailableError("NOAA returned no precipitation observations")
    return Signal(
        symbol=symbol, name=f"{c.name} belt precipitation (last full month, station mean)",
        value=round(statistics.fmean(values), 2), unit="mm", window="1mo",
        as_of=month_end.replace(hour=0, minute=0, second=0, microsecond=0),
        source=f"NOAA CDO GSOM ({len(values)} stations)", data_mode="live",
    )


def _drought_signal(symbol: str, c: Commodity) -> Signal:
    start = datetime.now(timezone.utc) - timedelta(days=21)
    latest: list[tuple[datetime, float]] = []
    try:
        with httpx.Client(headers={"Accept": "application/json"}, timeout=60.0) as client:
            for fips in c.state_fips:
                resp = client.get(USDM_URL, params={
                    "aoi": fips, "startdate": f"{start.month}/{start.day}/{start.year}",
                    "enddate": "12/31/2099", "statisticsType": "1",
                })
                resp.raise_for_status()
                rows = resp.json()
                if rows:
                    row = max(rows, key=lambda r: r["mapDate"])
                    latest.append((datetime.fromisoformat(row["mapDate"]), float(row["d1"])))
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise SourceUnavailableError(str(exc)) from exc
    if not latest:
        raise SourceUnavailableError("Drought Monitor returned no rows")
    return Signal(
        symbol=symbol, name=f"{c.name} belt area in moderate-or-worse drought (D1+, state mean)",
        value=round(statistics.fmean(v for _, v in latest), 2), unit="percent", window="weekly",
        as_of=max(d for d, _ in latest).replace(tzinfo=timezone.utc),
        source="US Drought Monitor", data_mode="live",
    )


def fetch_live(symbol: str) -> list[Signal]:
    c = COMMODITIES[symbol.upper()]
    token = get_settings().noaa_cdo_token
    builders = [lambda: _futures_signal(symbol, c), lambda: _drought_signal(symbol, c)]
    if token:
        builders.append(lambda: _precipitation_signal(symbol, c, token))
    signals: list[Signal] = []
    for build in builders:
        try:
            signals.append(build())
        except SourceUnavailableError:
            continue  # one component down shouldn't discard the others
    if not signals:
        raise SourceUnavailableError(f"no live commodity signals available for {symbol}")
    return signals


def fetch_sample(symbol: str) -> list[Signal]:
    return [
        Signal(
            symbol=symbol.upper(), name=r["name"], value=r["value"], unit=r["unit"], window=r["window"],
            as_of=datetime.fromisoformat(r["as_of"].replace("Z", "+00:00")), source=r["source"], data_mode="sample",
        )
        for r in load_fixture(FIXTURE_FILE)
        if r.get("symbol", symbol).upper() == symbol.upper()
    ]


def fetch_result(symbol: str, allow_live: bool = True, fallback: bool = True) -> FetchResult:
    return resolve(lambda: fetch_live(symbol), lambda: fetch_sample(symbol), allow_live, fallback)


def fetch(symbol: str, allow_live: bool = True) -> tuple[list[Signal], str]:
    result = fetch_result(symbol, allow_live)
    return result.items, result.data_mode
