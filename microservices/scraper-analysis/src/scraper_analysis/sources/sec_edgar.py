"""SEC EDGAR adapter (Form 4 / 8-K). Free, no signup -- SEC only requires a
descriptive User-Agent identifying the requester (see
https://www.sec.gov/os/webmaster-faq#developers).

v1 scope: reads the per-company `submissions` JSON feed and surfaces recent
Form 4 / 8-K filings as evidence. It does not parse Form 4 XML line items
(shares/price) yet -- that is a documented follow-up, not silently skipped.
"""

from datetime import datetime, timedelta, timezone
from typing import ClassVar
from xml.etree import ElementTree

import httpx

from ..config import get_settings
from .base import RawRecord, SourceAdapter, SourceUnavailableError
from . import sec_tickers
from .form4 import parse_form4

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
RELEVANT_FORMS = {"4", "8-K"}

# SEC's "recent" filings array holds up to ~1000 entries per company, going
# back years -- a large filer like Apple has hundreds of Form 4s in there.
# Without bounding this, one ingestion call pulls hundreds of stale records
# and (via the storage layer's per-record embedding call) can exhaust the
# Akamai inference rate limit in seconds. Cap to recent, demo-relevant
# filings only.
MAX_FILING_AGE_DAYS = 30
MAX_RECORDS = 10


class SecEdgarAdapter(SourceAdapter):
    name: ClassVar[str] = "sec_edgar"
    source_type: ClassVar[str] = "sec_filing"
    fixture_file: ClassVar[str] = "sec_form4_sample.json"

    def fetch_live(self, symbol: str) -> list[RawRecord]:
        settings = get_settings()
        headers = {"User-Agent": settings.sec_edgar_user_agent}
        try:
            with httpx.Client(headers=headers, timeout=10.0) as client:
                cik = self._lookup_cik(client, symbol)
                if cik is None:
                    raise SourceUnavailableError(f"no CIK found for symbol {symbol}")
                resp = client.get(SUBMISSIONS_URL.format(cik=cik))
                resp.raise_for_status()
                data = resp.json()
                records = self._build_records(data, cik, symbol)
                # Only the capped, newest records get their Form 4 XML
                # fetched, so request volume stays bounded (SEC asks for
                # <= 10 req/s; this is at most MAX_RECORDS sequential calls).
                for record in records:
                    if record.payload["form_type"] == "4":
                        self._enrich_form4(client, record, cik)
                return records
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceUnavailableError(str(exc)) from exc

    @staticmethod
    def _enrich_form4(client: httpx.Client, record: RawRecord, cik: int) -> None:
        """Best-effort: on any failure the record stays metadata-only rather
        than being dropped -- a filing we know exists is still evidence."""
        accession_nodash = record.payload["accession_number"].replace("-", "")
        raw_name = record.payload["primary_document"].split("/")[-1]  # strip the xsl render dir
        try:
            resp = client.get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/{raw_name}")
            resp.raise_for_status()
            parsed = parse_form4(resp.text)
        except (httpx.HTTPError, ElementTree.ParseError):
            return
        record.payload["form4"] = parsed
        if parsed.get("transaction_date"):
            record.observed_at = datetime.fromisoformat(parsed["transaction_date"]).replace(tzinfo=timezone.utc)

    def _build_records(self, data: dict, cik: int, symbol: str) -> list[RawRecord]:
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])
        items = recent.get("items", [""] * len(forms))

        records: list[RawRecord] = []
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=MAX_FILING_AGE_DAYS)
        for form, filing_date, accession, primary_doc, item in zip(
            forms, dates, accessions, primary_docs, items
        ):
            if form not in RELEVANT_FORMS:
                continue
            published_at = datetime.fromisoformat(filing_date).replace(tzinfo=timezone.utc)
            if published_at < cutoff:
                continue
            accession_nodash = accession.replace("-", "")
            url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                f"{accession_nodash}/{primary_doc}"
            )
            records.append(
                RawRecord(
                    source_name=self.name,
                    source_type=self.source_type,
                    symbol=symbol,
                    payload={
                        "form_type": form,
                        "items": item,
                        "accession_number": accession,
                        "primary_document": primary_doc,
                        "company_name": data.get("name"),
                    },
                    retrieved_at=now,
                    published_at=published_at,
                    observed_at=published_at,
                    url=url,
                )
            )
        records.sort(key=lambda r: r.published_at, reverse=True)
        return records[:MAX_RECORDS]

    @staticmethod
    def _lookup_cik(client: httpx.Client, symbol: str) -> int | None:
        info = sec_tickers.lookup(symbol, client)  # cached: not re-downloaded on every ingest
        return info.cik if info else None
