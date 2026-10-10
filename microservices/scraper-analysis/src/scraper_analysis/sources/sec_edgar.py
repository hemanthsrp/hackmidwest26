"""SEC EDGAR adapter (Form 4 / 8-K). Free, no signup -- SEC only requires a
descriptive User-Agent identifying the requester (see
https://www.sec.gov/os/webmaster-faq#developers).

v1 scope: reads the per-company `submissions` JSON feed and surfaces recent
Form 4 / 8-K filings as evidence. It does not parse Form 4 XML line items
(shares/price) yet -- that is a documented follow-up, not silently skipped.
"""

from datetime import datetime, timedelta, timezone
from typing import ClassVar

import httpx

from ..config import get_settings
from .base import RawRecord, SourceAdapter, SourceUnavailableError

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
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
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceUnavailableError(str(exc)) from exc

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
        resp = client.get(TICKERS_URL)
        resp.raise_for_status()
        for entry in resp.json().values():
            if entry.get("ticker", "").upper() == symbol.upper():
                return int(entry["cik_str"])
        return None
