from datetime import datetime, timezone

from scraper_analysis.pipeline.normalize import normalize
from scraper_analysis.sources.base import RawRecord
from scraper_analysis.sources.form4 import parse_form4
from scraper_analysis.sources.sec_edgar import SecEdgarAdapter

# Trimmed from a real Apple Form 4 (2026-10-06): one 10b5-1 open-market sale.
SALE_XML = """<?xml version="1.0"?>
<ownershipDocument>
  <periodOfReport>2026-10-06</periodOfReport>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Newstead Jennifer</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>false</isDirector><isOfficer>true</isOfficer>
      <officerTitle>SVP, GC and Government Affairs</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <aff10b5One>true</aff10b5One>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>2399</value></transactionShares>
        <transactionPricePerShare><value>332.01</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""

MIXED_XML = """<ownershipDocument>
  <periodOfReport>2026-10-01</periodOfReport>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Doe Jane</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>100</value></transactionShares>
        <transactionPricePerShare><value>10.5</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>F</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>40</value></transactionShares>
        <transactionPricePerShare><value>10.5</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""


def test_parse_open_market_sale():
    f = parse_form4(SALE_XML)
    assert f["owner"] == "Newstead Jennifer"
    assert f["role"] == "SVP, GC and Government Affairs"
    assert f["is_10b5_1"] is True
    assert f["sell_shares"] == 2399
    assert f["sell_value_usd"] == round(2399 * 332.01, 2)
    assert f["buy_shares"] == 0
    assert f["transaction_date"] == "2026-10-06"


def test_tax_withholding_is_not_counted_as_selling():
    f = parse_form4(MIXED_XML)
    assert f["buy_shares"] == 100
    assert f["sell_shares"] == 0  # code F (tax withholding) is not a sale
    assert f["other_codes"] == {"F": 40.0}
    assert f["role"] == "Director"
    assert f["is_10b5_1"] is False


def _record(form4):
    payload = {"form_type": "4", "company_name": "Apple Inc."}
    if form4:
        payload["form4"] = form4
    return RawRecord(
        source_name="sec_edgar", source_type="sec_filing", symbol="AAPL", payload=payload,
        retrieved_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
        published_at=datetime(2026, 10, 8, tzinfo=timezone.utc),
        observed_at=datetime(2026, 10, 6, tzinfo=timezone.utc), url="https://sec.example/f4",
    )


def test_normalize_form4_title_and_details():
    ev = normalize(_record(parse_form4(SALE_XML)), "live")
    assert "sold 2,399 shares" in ev.title
    assert "10b5-1" in ev.title
    assert ev.details["sell_shares"] == 2399
    assert ev.details["is_10b5_1"] is True
    assert ev.credibility.verified_filing is True


def test_normalize_mixed_form4_mentions_buy_only():
    ev = normalize(_record(parse_form4(MIXED_XML)), "live")
    assert "bought 100 shares" in ev.title
    assert "sold" not in ev.title


def test_normalize_form4_without_xml_falls_back_to_metadata_title():
    ev = normalize(_record(None), "live")
    assert ev.title == "Apple Inc. filed Form 4"
    assert ev.details == {"form_type": "4"}


def test_sample_fixture_exercises_direction_aware_path():
    records = SecEdgarAdapter().fetch_sample("AAPL")
    form4 = next(r for r in records if r.payload["form_type"] == "4")
    ev = normalize(form4, "sample")
    assert "sold" in ev.title and ev.details["sell_shares"] == 2399
