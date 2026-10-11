"""House of Representatives Periodic Transaction Reports (PTRs), from the
Clerk's public financial-disclosure site. Live-verified 2026-10-10.

How it works: the Clerk publishes a yearly index (a small zip holding XML:
member, filing type, filing date, DocID) and one PDF per filing. We read the
index, take the newest PTRs (FilingType "P") inside a short lookback, download
each PDF, and extract the transaction rows with pdfplumber. The e-filed PDFs
have a real text layer, so no OCR is involved -- the README's "vision LLM"
fallback is not needed for these.

Limits, stated rather than hidden:
- Scanned/paper filings have no text layer and are skipped (logged), not OCR'd.
- Rows are matched by ticker. Assets with no ticker (bonds, funds named only
  in words) are ignored, so this under-counts rather than guesses.
- Only the newest MAX_FILINGS_TO_SCAN filings in the lookback are read, the
  same bounding rule as the Senate adapter and for the same reason: one
  request per filing, and an unbounded scan is slow and abusive to a
  government server. Parsed PDFs are cached in-process so scanning for a
  second symbol, or the next scheduled run, re-reads nothing.
- Like the Senate side, this is public-record data under the Ethics in
  Government Act; 5 U.S.C. app. section 105(c) restricts using these reports
  for unlawful or commercial purposes, credit decisions or solicitation. A
  research/demo pipeline is within that, but this is not legal advice.
"""

import io
import logging
import re
import time
import zipfile
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import ClassVar
from xml.etree import ElementTree

import httpx

from ..config import get_settings
from .base import RawRecord, SourceAdapter, SourceUnavailableError

logger = logging.getLogger(__name__)

BASE = "https://disclosures-clerk.house.gov/public_disc"
INDEX_URL = BASE + "/financial-pdfs/{year}FD.zip"
PDF_URL = BASE + "/ptr-pdfs/{year}/{doc_id}.pdf"

LOOKBACK_DAYS = 45
MAX_FILINGS_TO_SCAN = 30
INDEX_TTL_SECONDS = 3600
PDF_CACHE_SIZE = 256

TYPE_LABELS = {"P": "Purchase", "S": "Sale (Full)", "S (partial)": "Sale (Partial)", "E": "Exchange"}
OWNER_LABELS = {"SP": "Spouse", "DC": "Dependent Child", "JT": "Joint"}

_ANCHOR_RE = re.compile(
    r"(?P<type>S \(partial\)|S|P|E)\s+(?P<tx>\d{2}/\d{2}/\d{4})\s+(?P<notified>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<amount>\$[\d,]+\s*-\s*\$[\d,]+|\$[\d,]+\s*-|Over\s+\$[\d,]+)"
)
_MONEY_RE = re.compile(r"\$[\d,]+")
_MARKER_RE = re.compile(r"^(F\s*S|S\s*O|D|C|L)\s*:")  # filing-status / sub-owner / description / comment / location blocks
_TICKER_PAREN_RE = re.compile(r"\(([A-Z]{1,5}(?:[./-][A-Z])?)\)")
_TICKER_BARE_RE = re.compile(r"^([A-Z]{1,5}(?:[./-][A-Z])?)\s*\[")
_ASSET_TYPE_RE = re.compile(r"\[([A-Z]{2})\]")
_OWNER_RE = re.compile(r"^(SP|DC|JT)\s+")
MAX_CONTINUATION_LINES = 3


@dataclass(frozen=True)
class HouseFiling:
    doc_id: str
    year: int
    filed: datetime
    member: str


def parse_index(xml_text: str) -> list[HouseFiling]:
    """PTR entries only (FilingType 'P'); everything else in the index
    (candidate reports, extensions, amendments) is not a trade list."""
    filings = []
    for m in ElementTree.fromstring(xml_text).findall("Member"):
        if (m.findtext("FilingType") or "").strip() != "P":
            continue
        try:
            filed = datetime.strptime((m.findtext("FilingDate") or "").strip(), "%m/%d/%Y").replace(tzinfo=timezone.utc)
            year = int((m.findtext("Year") or "").strip())
        except ValueError:
            continue
        name = " ".join(
            p for p in [(m.findtext("First") or "").strip(), (m.findtext("Last") or "").strip(),
                        (m.findtext("Suffix") or "").strip()] if p
        )
        name = re.sub(r"\b(\w+)( \1\b)+", r"\1", name)  # index sometimes repeats a word, e.g. 'Scott Scott'
        doc_id = (m.findtext("DocID") or "").strip()
        if doc_id and name:
            filings.append(HouseFiling(doc_id, year, filed, name))
    return filings


def _normalize_ticker(raw: str) -> str:
    return raw.replace("/", ".").replace("-", ".")


def parse_ptr_text(text: str) -> list[dict]:
    """Extract transaction rows from a PTR's text. A row is anchored by its
    'type, transaction date, notification date, amount' run; the asset name
    and ticker sit on the same line and up to a few continuation lines, and
    description blocks (F S:, S O:, D:, C:, L:) end the row and are never
    rows themselves."""
    lines = [ln.strip() for ln in text.replace("\x00", "").split("\n")]
    rows = []
    for i, line in enumerate(lines):
        if _MARKER_RE.match(line):
            # Field blocks (F S:, S O:, D:, C:, L:) are free text written by the
            # filer; one that happens to contain a "type date date amount" run
            # is still a description, never a transaction.
            continue
        m = _ANCHOR_RE.search(line)
        if not m:
            continue
        left = line[: m.start()].strip()
        asset_lines = [left]
        for nxt in lines[i + 1 : i + 1 + MAX_CONTINUATION_LINES]:
            if not nxt or _MARKER_RE.match(nxt) or _ANCHOR_RE.search(nxt):
                break
            asset_lines.append(nxt)
        amount = re.sub(r"\s+", " ", m.group("amount"))
        if amount.endswith("-"):
            # The range wrapped ("$15,001 -" then "$50,000" on a later line):
            # complete it from the continuation lines instead of dropping the row.
            upper = next((_MONEY_RE.search(ln) for ln in asset_lines[1:] if _MONEY_RE.search(ln)), None)
            if upper is None:
                continue  # incomplete amount: skip rather than guess
            amount = f"{amount} {upper.group(0)}"
        asset_text = " ".join(part for part in asset_lines if part)
        asset_text = _MONEY_RE.sub("", asset_text)  # drop any wrapped amount fragment from the asset name

        owner = "Self"
        om = _OWNER_RE.match(asset_text)
        if om:
            owner = OWNER_LABELS[om.group(1)]
            asset_text = asset_text[om.end():]

        tm = _TICKER_PAREN_RE.search(asset_text)
        raw_ticker = tm.group(1) if tm else None
        if raw_ticker is None:
            bm = next((b for b in (_TICKER_BARE_RE.match(p) for p in asset_lines) if b), None)
            raw_ticker = bm.group(1) if bm else None
        if raw_ticker is None:
            continue  # no usable ticker: skip rather than guess

        ac = _ASSET_TYPE_RE.search(asset_text)
        rows.append(
            {
                "ticker": _normalize_ticker(raw_ticker),
                "asset_name": _TICKER_PAREN_RE.sub("", _ASSET_TYPE_RE.sub("", asset_text)).strip(" -"),
                "asset_type_code": ac.group(1) if ac else None,
                "transaction_type": TYPE_LABELS[m.group("type")],
                "transaction_date": m.group("tx"),
                "notification_date": m.group("notified"),
                "amount_range": amount,
                "owner": owner,
            }
        )
    return rows


_pdf_cache: "OrderedDict[tuple[int, str], list[dict]]" = OrderedDict()
_index_cache: dict[int, tuple[float, list[HouseFiling]]] = {}


def _extract_pdf_text(content: bytes) -> str:
    import pdfplumber  # imported lazily: heavy, and only needed for live House scans

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages)


def _load_index(client: httpx.Client, year: int) -> list[HouseFiling]:
    cached = _index_cache.get(year)
    if cached and time.monotonic() - cached[0] < INDEX_TTL_SECONDS:
        return cached[1]
    resp = client.get(INDEX_URL.format(year=year))
    resp.raise_for_status()
    try:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".xml")), None)
            if name is None:
                raise SourceUnavailableError("House FD index zip has no XML")
            filings = parse_index(z.read(name).decode("utf-8-sig"))
    except (UnicodeDecodeError, zipfile.BadZipFile, zipfile.LargeZipFile, ElementTree.ParseError,
            KeyError, ValueError, EOFError, OSError) as exc:
        # A corrupt index is an unavailable source, not a crash. Fixed text:
        # decoder/parser messages quote upstream bytes and are not returned.
        raise SourceUnavailableError(f"House FD index unreadable ({type(exc).__name__})") from exc
    _index_cache[year] = (time.monotonic(), filings)
    return filings


def _load_transactions(client: httpx.Client, filing: HouseFiling) -> list[dict] | None:
    """Parsed rows for one filing, cached. None = could not be read right now
    (network); [] = read fine but nothing usable (e.g. no text layer)."""
    key = (filing.year, filing.doc_id)
    if key in _pdf_cache:
        _pdf_cache.move_to_end(key)
        return _pdf_cache[key]
    try:
        resp = client.get(PDF_URL.format(year=filing.year, doc_id=filing.doc_id))
        resp.raise_for_status()
        text = _extract_pdf_text(resp.content)
    except httpx.HTTPError:
        return None
    except Exception:  # pdfminer raises assorted errors on malformed PDFs
        logger.info("House PTR %s unreadable; skipping", filing.doc_id, exc_info=True)
        text = ""
    if not text.strip():
        logger.info("House PTR %s has no text layer (scanned?); skipping", filing.doc_id)
    rows = parse_ptr_text(text)
    _pdf_cache[key] = rows
    while len(_pdf_cache) > PDF_CACHE_SIZE:
        _pdf_cache.popitem(last=False)
    return rows


def _parse_date(value: str | None) -> datetime | None:
    try:
        return datetime.strptime((value or "").strip(), "%m/%d/%Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _validate_trade_date(row: dict, filed: datetime, now: datetime) -> tuple[datetime | None, str | None]:
    """(trade date, None) when usable, else (None, reason). A trade cannot
    happen after it was reported, after the member was notified of it, or
    after we retrieved the report; such dates are filer/parse errors and
    would yield a negative or meaningless reporting lag."""
    traded = _parse_date(row.get("transaction_date"))
    if traded is None:
        return None, "unparseable"
    if traded > now:
        return None, "future"
    if traded.date() > filed.date():
        return None, "after_filing"
    notified = _parse_date(row.get("notification_date"))
    if notified is not None and traded > notified:
        return None, "after_notification"
    return traded, None


def _with_occurrence(rows: list[dict]) -> list[tuple[dict, int]]:
    seen: dict[tuple, int] = {}
    out = []
    for row in rows:
        key = (row.get("owner"), row.get("asset_name"), row.get("ticker"), row.get("transaction_type"),
               row.get("transaction_date"), row.get("amount_range"))
        out.append((row, seen.get(key, 0)))
        seen[key] = seen.get(key, 0) + 1
    return out


class HouseClerkAdapter(SourceAdapter):
    name: ClassVar[str] = "house_clerk"
    source_type: ClassVar[str] = "congressional_disclosure"
    fixture_file: ClassVar[str] = "congressional_house_sample.json"

    def fetch_live(self, symbol: str) -> list[RawRecord]:
        headers = {"User-Agent": get_settings().sec_edgar_user_agent}
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=LOOKBACK_DAYS)
        try:
            with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
                filings: list[HouseFiling] = []
                for year in sorted({now.year, cutoff.year}):
                    filings += _load_index(client, year)
                recent = sorted((f for f in filings if f.filed >= cutoff), key=lambda f: f.filed, reverse=True)
                recent = recent[:MAX_FILINGS_TO_SCAN]

                records: list[RawRecord] = []
                unreadable = 0
                for filing in recent:
                    rows = _load_transactions(client, filing)
                    if rows is None:
                        unreadable += 1
                        continue
                    records += [self._record(filing, row, occurrence, symbol, now)
                                for row, occurrence in _with_occurrence(rows)
                                if row["ticker"].upper() == symbol.upper()]
                if recent and unreadable == len(recent):
                    raise SourceUnavailableError("no House PTR PDF could be downloaded")
                return records
        except (httpx.HTTPError, zipfile.BadZipFile, ElementTree.ParseError, UnicodeDecodeError) as exc:
            raise SourceUnavailableError(f"House Clerk: {type(exc).__name__}") from exc

    def _record(self, filing: HouseFiling, row: dict, occurrence: int, symbol: str, now: datetime) -> RawRecord:
        traded, date_issue = _validate_trade_date(row, filing.filed, now)
        return RawRecord(
            source_name="House Clerk",
            source_type=self.source_type,
            symbol=symbol,
            payload={
                "chamber": "House",
                "filer_name": filing.member,
                "owner": row["owner"],
                "ticker": row["ticker"],
                "asset_name": row["asset_name"],
                "asset_type": row["asset_type_code"],
                "transaction_type": row["transaction_type"],
                "amount_range": row["amount_range"],
                "transaction_date": row["transaction_date"],
                "date_issue": date_issue,
                # Nth identical row (same owner/asset/type/date/amount) in this
                # filing, so two real lots never collapse into one evidence ID.
                "filing_row": occurrence,
            },
            retrieved_at=now,
            published_at=filing.filed,
            # No valid trade date -> no observed_at, so no reporting lag or
            # timing class is computed from a date we know is wrong.
            observed_at=traded,
            url=PDF_URL.format(year=filing.year, doc_id=filing.doc_id),
        )
