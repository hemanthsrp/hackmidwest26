from scraper_analysis.sources.congressional import SenateEfdAdapter, _parse_transactions

# Shape matches the real efdsearch.senate.gov PTR detail table, live-verified
# 2026-10-10: #, Transaction Date, Owner, Ticker, Asset Name, Asset Type,
# Type, Amount, Comment (9 columns).
SAMPLE_TABLE_HTML = """
<table class="table table-striped">
<thead><tr class="header">
<th>#</th><th>Transaction Date</th><th>Owner</th><th>Ticker</th>
<th>Asset Name</th><th>Asset Type</th><th>Type</th><th>Amount</th><th>Comment</th>
</tr></thead>
<tbody>
<tr>
<td>1</td>
<td>09/15/2026</td>
<td>Spouse</td>
<td>AAPL</td>
<td>Apple Inc. Common Stock</td>
<td>Stock</td>
<td>Purchase</td>
<td>$15,001 - $50,000</td>
<td>--</td>
</tr>
<tr>
<td>2</td>
<td>09/16/2026</td>
<td>Child</td>
<td>--</td>
<td>DELL INTL LLC/EMC CORP</td>
<td>Corporate Bond</td>
<td>Purchase</td>
<td>$1,001 - $15,000</td>
<td>--</td>
</tr>
</tbody>
</table>
"""


def test_parse_transactions_extracts_rows_with_a_ticker():
    transactions = _parse_transactions(SAMPLE_TABLE_HTML)
    assert len(transactions) == 1  # the bond row (ticker "--") is excluded
    tx = transactions[0]
    assert tx["ticker"] == "AAPL"
    assert tx["transaction_date"] == "09/15/2026"
    assert tx["owner"] == "Spouse"
    assert tx["transaction_type"] == "Purchase"
    assert tx["amount"] == "$15,001 - $50,000"


def test_parse_transactions_skips_non_data_rows():
    assert _parse_transactions("<table><tr><th>Header</th></tr></table>") == []


def test_fetch_sample_returns_fixture_for_known_symbol():
    adapter = SenateEfdAdapter()
    records = adapter.fetch_sample("AAPL")
    assert len(records) == 1
    assert records[0].symbol == "AAPL"
    assert records[0].source_type == "congressional_disclosure"
    assert records[0].payload["ticker"] == "AAPL"


def test_fetch_falls_back_to_sample_when_live_disallowed():
    adapter = SenateEfdAdapter()
    records, data_mode = adapter.fetch("AAPL", allow_live=False)
    assert data_mode == "sample"
    assert len(records) == 1
