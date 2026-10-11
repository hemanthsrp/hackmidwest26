"""House of Representatives Periodic Transaction Reports (PTRs), from the
Clerk's public financial-disclosure site. Live-verified 2026-10-10.

How it works: the Clerk publishes a yearly index (a small zip holding XML:
member, filing type, filing date, DocID) and one PDF per filing. We read the
index, take the newest PTRs (FilingType "P") inside a short lookback, download
each PDF, and extract the transaction rows with pdfplumber. The e-filed PDFs
have a real text layer, so no OCR is involved -- the README's "vision LLM"
fallback is not needed for these.

Limits, stated rather than hidden:
- Scanned/paper filings have no text layer and are skipped, not OCR'd. Those,
  unreadable PDFs and failed downloads are counted and reported on the live
  result (FetchResult.error, e.g. "partial: 3 of 30 House PTR filings
  skipped (...)"), so partial coverage is never presented as complete.
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
from .base import LiveRecords, RawRecord, SourceAdapter, SourceUnavailableError

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

# (?<!\S): the type code is its own word, so "...ETFS 03/17/2026" is not a sale.
_ANCHOR_RE = re.compile(
    r"(?<!\S)(?P<type>S \(partial\)|S|P|E)\s+(?P<tx>\d{2}/\d{2}/\d{4})\s+(?P<notified>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<amount>\$[\d,]+\s*-\s*\$[\d,]+|\$[\d,]+\s*-|Over\s+\$[\d,]+)"
)
_MONEY_RE = re.compile(r"\$[\d,]+")
_MARKER_RE = re.compile(r"^(F\s*S|S\s*O|D|C|L)\s*:")  # filing-status / sub-owner / description / comment / location blocks
_FREE_TEXT_MARKER_RE = re.compile(r"^(D|C)\s*:")  # description / comment: filer prose, can wrap many lines
_TICKER_PAREN_RE = re.compile(r"\(([A-Z]{1,5}(?:[./-][A-Z])?)\)")
_TICKER_BARE_RE = re.compile(r"^([A-Z]{1,5}(?:[./-][A-Z])?)\s*\[")
_ASSET_TYPE_RE = re.compile(r"\[([A-Z]{2})\]")
_OWNER_RE = re.compile(r"^(SP|DC|JT)\s+")
MAX_CONTINUATION_LINES = 3
# Column geometry of the e-filed PTR form (pdfplumber word x0, points). Live
# PTRs put the header words "Transaction" (type), "Date", "Notification" and
# "Amount" at x0 262/326/382/446, and each row's type/date/date/amount tokens
# within ~2pt of those. Description text wraps at the asset column and flows
# like a sentence, so its tokens land wherever the prose puts them.
COLUMN_TOLERANCE_PT = 8.0
LINE_TOLERANCE_PT = 3.0


@dataclass(frozen=True)
class PtrLine:
    """One text line of a PTR. anchor_aligned says whether the line's
    "type date date amount" run sits under the form's column headers: True /
    False when word positions are known, None for plain text (or when no
    header row was found), in which case the stricter text-only rules apply."""

    text: str
    anchor_aligned: bool | None = None


def _header_columns(words: list[dict]) -> dict[str, float] | None:
    texts = [w["text"] for w in words]
    if not all(t in texts for t in ("Transaction", "Notification", "Amount")):
        return None
    i = texts.index("Transaction")
    date_i = next((j for j in range(i + 1, len(texts)) if texts[j] == "Date"), None)
    if date_i is None:
        return None
    return {"type": words[i]["x0"], "tx": words[date_i]["x0"],
            "notified": words[texts.index("Notification")]["x0"], "amount": words[texts.index("Amount")]["x0"]}


def _anchor_alignment(words: list[dict], columns: dict[str, float] | None) -> tuple[str, bool | None]:
    """(line text, alignment) for one line of positioned words."""
    starts, pos = [], 0
    for w in words:
        starts.append(pos)
        pos += len(w["text"]) + 1
    text = " ".join(w["text"] for w in words)
    if columns is None:
        return text, None
    m = _ANCHOR_RE.search(text)
    if m is None:
        return text, None
    for group in ("type", "tx", "notified", "amount"):
        if m.start(group) not in starts:
            return text, False  # token glued inside a word: not a form column
        x0 = words[starts.index(m.start(group))]["x0"]
        if abs(x0 - columns[group]) > COLUMN_TOLERANCE_PT:
            return text, False
    return text, True


def lines_from_pages(pages: list[list[dict]]) -> list[PtrLine]:
    """Group pdfplumber words ({"x0", "top", "text"}) into reading-order
    lines, tagging each anchor run with whether it is column-aligned. The
    header row's column positions carry over to later pages (the form
    template is the same on every page; a repeated header refreshes them)."""
    out: list[PtrLine] = []
    columns: dict[str, float] | None = None
    for words in pages:
        # NULs are glyph padding in the form's field labels ("F\x00\x00 S\x00:").
        words = [{**w, "text": w["text"].replace("\x00", "")} for w in words]
        words = [w for w in words if w["text"]]
        groups: list[list[dict]] = []
        for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
            if groups and abs(w["top"] - groups[-1][0]["top"]) <= LINE_TOLERANCE_PT:
                groups[-1].append(w)
            else:
                groups.append([w])
        for g in groups:
            g.sort(key=lambda w: w["x0"])
            columns = _header_columns(g) or columns
            text, aligned = _anchor_alignment(g, columns)
            out.append(PtrLine(text, aligned))
    return out


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
    """Plain-text entry point (no word positions): see parse_ptr_lines."""
    return parse_ptr_lines([PtrLine(ln) for ln in text.replace("\x00", "").split("\n")])


def parse_ptr_lines(ptr_lines: list[PtrLine]) -> list[dict]:
    """Extract transaction rows from a PTR. A row is anchored by its 'type,
    transaction date, notification date, amount' run; the asset name, owner
    and ticker sit on the same line (before the run, or after it) and up to
    a few continuation lines. Field blocks (F S:, S O:, D:, C:, L:) end the
    row and are never rows themselves, and they can wrap onto later lines
    that carry no marker.

    Deciding where a block ends, strongest signal first:
    - word positions (live PDFs): a trade-shaped line is a row only if its
      type/date/date/amount tokens sit under the form's column headers
      (PtrLine.anchor_aligned True). Wrapped description prose that happens
      to contain such a run -- even with "(AAPL) [ST]" -- is not aligned and
      is skipped;
    - plain text (no positions): after a field marker (F S:, S O:, L:) a new
      row also needs the asset-type code the form prints for every asset
      ("[ST]", "[OP]", ...). After a free-text block (D:, C:) NO trade-shaped
      line is a row until the next field marker: plain text cannot tell a
      real row from description prose that copies one -- even one with an
      owner code and "[ST]" (PR #17 review) -- so the row right after a
      description is skipped (under-count) rather than risk a fabricated
      trade. The next row after that row's own "F S:" line parses again.
    """
    lines = [PtrLine(ln.text.replace("\x00", "").strip(), ln.anchor_aligned) for ln in ptr_lines]
    rows = []
    block = None  # None outside a field block, else "free" (D:/C:) or "field"
    for i, pl in enumerate(lines):
        line = pl.text
        if _MARKER_RE.match(line):
            block = "free" if _FREE_TEXT_MARKER_RE.match(line) else "field"
            continue
        m = _ANCHOR_RE.search(line)
        if not m:
            continue
        if pl.anchor_aligned is False:
            continue  # trade-shaped prose (not under the form columns): never a row
        left = line[: m.start()].strip()
        trailing = line[m.end():].strip()  # e.g. "... $15,000 (AAPL) [ST]"
        asset_lines = [left] + ([trailing] if trailing else [])
        for nxt in lines[i + 1 : i + 1 + MAX_CONTINUATION_LINES]:
            if not nxt.text or _MARKER_RE.match(nxt.text) or _ANCHOR_RE.search(nxt.text):
                break
            asset_lines.append(nxt.text)
        if block is not None and pl.anchor_aligned is None:
            if block == "free":
                continue  # could be description/comment prose copying a row: skip, never guess
            if not any(_ASSET_TYPE_RE.search(part) for part in asset_lines):
                continue  # trade-shaped text inside a field block: ambiguous, skip
        block = None  # a real asset row starts here, even if it is skipped below
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
                "asset_name": " ".join(_TICKER_PAREN_RE.sub("", _ASSET_TYPE_RE.sub("", asset_text)).split()).strip(" -"),
                "asset_type_code": ac.group(1) if ac else None,
                "transaction_type": TYPE_LABELS[m.group("type")],
                "transaction_date": m.group("tx"),
                "notification_date": m.group("notified"),
                "amount_range": amount,
                "owner": owner,
            }
        )
    return rows


# (rows, issue): issue is None, ISSUE_NO_TEXT or ISSUE_UNREADABLE. Failed
# downloads are not cached, so they are retried next run.
_pdf_cache: "OrderedDict[tuple[int, str], tuple[list[dict], str | None]]" = OrderedDict()
ISSUE_NO_TEXT = "no text layer"
ISSUE_UNREADABLE = "unreadable"
ISSUE_DOWNLOAD = "download failed"
_index_cache: dict[int, tuple[float, list[HouseFiling]]] = {}


def _extract_pdf_lines(content: bytes) -> list[PtrLine]:
    import pdfplumber  # imported lazily: heavy, and only needed for live House scans

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return lines_from_pages([page.extract_words() for page in pdf.pages])


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
    (network); [] = read fine but nothing usable (e.g. no text layer -- see
    _filing_issue for why)."""
    key = (filing.year, filing.doc_id)
    if key in _pdf_cache:
        _pdf_cache.move_to_end(key)
        return _pdf_cache[key][0]
    issue = None
    try:
        resp = client.get(PDF_URL.format(year=filing.year, doc_id=filing.doc_id))
        resp.raise_for_status()
        lines = _extract_pdf_lines(resp.content)
    except httpx.HTTPError:
        return None
    except Exception:  # pdfminer raises assorted errors on malformed PDFs
        logger.info("House PTR %s unreadable; skipping", filing.doc_id, exc_info=True)
        lines, issue = [], ISSUE_UNREADABLE
    if issue is None and not any(ln.text.strip() for ln in lines):
        logger.info("House PTR %s has no text layer (scanned?); skipping", filing.doc_id)
        issue = ISSUE_NO_TEXT
    rows = parse_ptr_lines(lines)
    _pdf_cache[key] = (rows, issue)
    while len(_pdf_cache) > PDF_CACHE_SIZE:
        _pdf_cache.popitem(last=False)
    return rows


def _filing_issue(filing: HouseFiling) -> str | None:
    """Why a filing that loaded yielded nothing usable (cached result only)."""
    cached = _pdf_cache.get((filing.year, filing.doc_id))
    return cached[1] if cached else None


def _coverage_note(issues: list[str], scanned: int) -> str | None:
    """Fixed-vocabulary summary of skipped filings; never upstream text or URLs."""
    if not issues:
        return None
    counts = {k: issues.count(k) for k in (ISSUE_NO_TEXT, ISSUE_UNREADABLE, ISSUE_DOWNLOAD) if k in issues}
    detail = ", ".join(f"{n} {k}" for k, n in counts.items())
    return f"partial: {len(issues)} of {scanned} House PTR filings skipped ({detail})"


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
    return traded, None


def _validate_notification_date(row: dict, traded: datetime | None, filed: datetime,
                                now: datetime) -> tuple[datetime | None, str | None]:
    """(notification date, None) when usable, else (None, reason). Checked
    like the trade date: a real calendar date, not in the future, not after
    the filing that reports it, and not before the trade it notifies of (only
    checked when the trade date is valid). An invalid notification date never
    invalidates a valid trade date; it only drops notification-derived values."""
    notified = _parse_date(row.get("notification_date"))
    if notified is None:
        return None, "unparseable"
    if notified > now:
        return None, "future"
    if notified.date() > filed.date():
        return None, "after_filing"
    if traded is not None and notified < traded:
        return None, "before_trade"
    return notified, None


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

    def fetch_live(self, symbol: str) -> LiveRecords:
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
                issues: list[str] = []
                for filing in recent:
                    rows = _load_transactions(client, filing)
                    if rows is None:
                        issues.append(ISSUE_DOWNLOAD)
                        continue
                    issue = _filing_issue(filing)
                    if issue is not None:
                        issues.append(issue)
                    records += [self._record(filing, row, occurrence, symbol, now)
                                for row, occurrence in _with_occurrence(rows)
                                if row["ticker"].upper() == symbol.upper()]
                if recent and issues.count(ISSUE_DOWNLOAD) == len(recent):
                    raise SourceUnavailableError("no House PTR PDF could be downloaded")
                return LiveRecords(records, note=_coverage_note(issues, len(recent)))
        except (httpx.HTTPError, zipfile.BadZipFile, ElementTree.ParseError, UnicodeDecodeError) as exc:
            raise SourceUnavailableError(f"House Clerk: {type(exc).__name__}") from exc

    def _record(self, filing: HouseFiling, row: dict, occurrence: int, symbol: str, now: datetime) -> RawRecord:
        traded, date_issue = _validate_trade_date(row, filing.filed, now)
        notified, notification_issue = _validate_notification_date(row, traded, filing.filed, now)
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
                # Validated separately: an invalid notification date is
                # reported here and yields no notification-derived values,
                # but never makes a valid trade date undated.
                "notification_date_reported": row.get("notification_date"),
                "notification_date": notified.date().isoformat() if notified else None,
                "notification_date_issue": notification_issue,
                "notification_lag_days": (notified - traded).days if notified and traded else None,
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
