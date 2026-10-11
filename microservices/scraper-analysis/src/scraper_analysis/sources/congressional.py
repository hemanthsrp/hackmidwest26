"""Senate electronic Financial Disclosure (eFD) adapter -- Periodic
Transaction Reports (PTRs). Public record mandated by the STOCK Act, not
copyrighted, not paywalled. Live-verified 2026-10-10: efdsearch.senate.gov
serves PTR transaction tables as plain HTML (date, owner, ticker, asset
name, type, amount range) -- no PDF/OCR needed for the Senate side.

Scope: Senate only. House of Representatives disclosures are frequently
scanned PDFs requiring pdfplumber/OCR per the README -- that's a real,
heavier follow-up, not silently skipped.

Access: the site requires accepting a public-use agreement before
searching (a session cookie + CSRF token, not a login). Every session must
also acknowledge the statutory restriction in 5 U.S.C. app. SS 105(c): this
data may not be used for any unlawful purpose, for a commercial purpose
other than news/communications, to determine credit-worthiness, or for
solicitation -- a research/demo pipeline is within those bounds, but this
is not legal advice and the restriction should stay visible, not buried.

No official API exists; Quiver Quantitative (the only notable third-party
aggregator) has no free API tier (checked 2026-10-10: $30+/mo) -- not
viable for a hackathon, so this talks to Senate's own search directly.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import ClassVar

import httpx

from ..config import get_settings
from .base import RawRecord, SourceAdapter, SourceUnavailableError

BASE_URL = "https://efdsearch.senate.gov"
HOME_URL = f"{BASE_URL}/search/home/"
SEARCH_URL = f"{BASE_URL}/search/report/data/"

PTR_REPORT_TYPE = "[11]"
LOOKBACK_DAYS = 60
# Bound detail-page fetches -- same lesson as the SEC EDGAR incident:
# an unbounded scan of every recent filing is slow and can look like
# abusive load against a government site. One search call always happens;
# only matching candidates get a detail-page fetch, capped here regardless.
MAX_FILINGS_TO_SCAN = 25

CSRF_RE = re.compile(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"')
HREF_RE = re.compile(r'href="([^"]+)"')
ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TAG_RE = re.compile(r"<[^<]+?>")


class SenateEfdAdapter(SourceAdapter):
    name: ClassVar[str] = "senate_efd"
    source_type: ClassVar[str] = "congressional_disclosure"
    fixture_file: ClassVar[str] = "congressional_sample.json"

    def fetch_live(self, symbol: str) -> list[RawRecord]:
        settings = get_settings()
        headers = {"User-Agent": settings.sec_edgar_user_agent}
        try:
            with httpx.Client(headers=headers, timeout=15.0, follow_redirects=True) as client:
                return self._fetch_with_session(client, symbol)
        except httpx.HTTPError as exc:
            raise SourceUnavailableError(str(exc)) from exc

    def _fetch_with_session(self, client: httpx.Client, symbol: str) -> list[RawRecord]:
        home_resp = client.get(HOME_URL)
        home_resp.raise_for_status()
        csrf_match = CSRF_RE.search(home_resp.text)
        if not csrf_match:
            raise SourceUnavailableError("could not find CSRF token on Senate eFD home page")
        csrf = csrf_match.group(1)

        agree_resp = client.post(
            HOME_URL,
            data={"csrfmiddlewaretoken": csrf, "prohibition_agreement": "1"},
            headers={"Referer": HOME_URL},
        )
        agree_resp.raise_for_status()

        csrftoken = client.cookies.get("csrftoken")
        if not csrftoken:
            raise SourceUnavailableError("no csrftoken cookie after accepting Senate eFD agreement")

        start_date = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%m/%d/%Y 00:00:00")
        search_resp = client.post(
            SEARCH_URL,
            data={
                "csrfmiddlewaretoken": csrftoken,
                "report_types": PTR_REPORT_TYPE,
                "filer_types": "[]",
                "submitted_start_date": start_date,
                "submitted_end_date": "",
                "candidate_state": "",
                "senator_state": "",
                "office_id": "",
                "first_name": "",
                "last_name": "",
                "start": "0",
                "length": str(MAX_FILINGS_TO_SCAN),
            },
            headers={"Referer": f"{BASE_URL}/search/", "X-CSRFToken": csrftoken},
        )
        search_resp.raise_for_status()
        rows = search_resp.json().get("data", [])[:MAX_FILINGS_TO_SCAN]

        now = datetime.now(timezone.utc)
        records: list[RawRecord] = []
        for row in rows:
            record_batch = self._scan_filing(client, row, symbol, now)
            records.extend(record_batch)
        return records

    def _scan_filing(self, client: httpx.Client, row: list, symbol: str, now: datetime) -> list[RawRecord]:
        first_name, last_name, _full, link_html, filed_date_str = row[:5]
        href_match = HREF_RE.search(link_html)
        if not href_match:
            return []
        try:
            detail_resp = client.get(f"{BASE_URL}{href_match.group(1)}")
            detail_resp.raise_for_status()
        except httpx.HTTPError:
            return []  # one bad filing shouldn't abort the whole scan

        filer_name = f"{first_name} {last_name}".strip()
        try:
            filed_date = datetime.strptime(filed_date_str, "%m/%d/%Y").replace(tzinfo=timezone.utc)
        except ValueError:
            filed_date = None

        records = []
        for tx in _parse_transactions(detail_resp.text):
            if tx["ticker"].upper() != symbol.upper():
                continue
            # Never substitute the filing date for an invalid trade date: the
            # record stays undated (observed_at=None) and says why, so no
            # reporting lag, timing class or divergence uses a wrong date.
            observed_at, date_issue = _validate_trade_date(tx["transaction_date"], filed_date, now)
            records.append(
                RawRecord(
                    source_name="Senate eFD",
                    source_type=self.source_type,
                    symbol=symbol,
                    payload={
                        "filer_name": filer_name,
                        "owner": tx["owner"],
                        "ticker": tx["ticker"],
                        "asset_name": tx["asset_name"],
                        "asset_type": tx["asset_type"],
                        "transaction_type": tx["transaction_type"],
                        "amount_range": tx["amount"],
                        "transaction_date": tx["transaction_date"],
                        "date_issue": date_issue,
                    },
                    retrieved_at=now,
                    published_at=filed_date,
                    observed_at=observed_at,
                    url=f"{BASE_URL}{href_match.group(1)}",
                )
            )
        return records


def _parse_transactions(html: str) -> list[dict]:
    transactions = []
    for row_html in ROW_RE.findall(html):
        cells = [TAG_RE.sub("", c).strip() for c in CELL_RE.findall(row_html)]
        if len(cells) != 9:
            continue  # not a transaction data row (header, nested tables, etc.)
        _idx, tx_date, owner, ticker, asset_name, asset_type, tx_type, amount, _comment = cells
        if not ticker or ticker == "--":
            continue  # no clean ticker (e.g. bonds) -- not usable evidence for a symbol query
        transactions.append(
            {
                "transaction_date": tx_date,
                "owner": owner,
                "ticker": ticker,
                "asset_name": re.sub(r"\s+", " ", asset_name).strip(),
                "asset_type": asset_type,
                "transaction_type": tx_type,
                "amount": amount,
            }
        )
    return transactions


def _validate_trade_date(
    value: str, filed: datetime | None, now: datetime
) -> tuple[datetime | None, str | None]:
    """(trade date, None) for a usable date, else (None, reason)."""
    traded = _parse_tx_date(value)
    if traded is None:
        return None, "unparseable or impossible trade date"
    if traded > now:
        return None, "trade date in the future"
    if filed is not None and traded > filed:
        return None, "trade date after filing date"
    return traded, None


def _parse_tx_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), "%m/%d/%Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
