"""Parses SEC Form 4 (insider transaction) XML into direction-aware
aggregates. Live-verified shape (Apple, 2026-10-06 filing).

Only transaction codes P (open-market purchase) and S (open-market sale)
count as directional insider flow. Everything else -- A (grant/award),
M (option exercise), F (shares withheld for tax), G (gift), etc. -- is
recorded under `other` and deliberately NOT treated as buying or selling:
an RSU vest withheld for taxes is not a bearish signal.

`is_10b5_1` flags trades made under a pre-scheduled Rule 10b5-1 plan. Those
are decided months earlier, so they say much less about current insider
conviction than a discretionary trade -- consumers should weight them down.

Dates: `periodOfReport` is the filing's reporting period, not necessarily
when the trades happened, and one Form 4 can cover trades on several days.
`transaction_date` is the EARLIEST per-transaction `transactionDate/value`
(when the insider first acted, which is what reporting lag is measured
from); `transaction_dates` lists every distinct trade date, and
`last_transaction_date` the latest. `periodOfReport` is used only when no
transaction carries a date, and is always kept as `period_of_report`.

`transactions` is the per-trade breakdown of the directional (P/S)
non-derivative rows, in document order: {date, code, shares, price,
value_usd}. Consumers that window by date (e.g. the divergence engine) must
value only the trades inside their window, not the filing totals.
"""

from xml.etree import ElementTree


def _text(node: ElementTree.Element | None, path: str) -> str | None:
    if node is None:
        return None
    found = node.find(path)
    return found.text.strip() if found is not None and found.text else None


def _num(value: str | None) -> float:
    try:
        return float(value) if value else 0.0
    except ValueError:
        return 0.0


def _date(value: str | None) -> str | None:
    """Form 4 dates are YYYY-MM-DD, occasionally with a timezone suffix
    (e.g. 2026-10-06-05:00). Keep the calendar date only."""
    return value[:10] if value and len(value) >= 10 else None


def parse_form4(xml_text: str) -> dict:
    root = ElementTree.fromstring(xml_text)
    rel = root.find("reportingOwner/reportingOwnerRelationship")
    role = _text(rel, "officerTitle")
    if not role:
        if _text(rel, "isDirector") in ("1", "true"):
            role = "Director"
        elif _text(rel, "isTenPercentOwner") in ("1", "true"):
            role = "10% owner"

    buy_shares = sell_shares = buy_value = sell_value = 0.0
    other: dict[str, float] = {}
    dates: set[str] = set()
    transactions: list[dict] = []
    for tx in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        tx_date = _date(_text(tx, "transactionDate/value"))
        if tx_date:
            dates.add(tx_date)
        code = _text(tx, "transactionCoding/transactionCode") or "?"
        shares = _num(_text(tx, "transactionAmounts/transactionShares/value"))
        price = _num(_text(tx, "transactionAmounts/transactionPricePerShare/value"))
        if code in ("P", "S"):
            transactions.append({"date": tx_date, "code": code, "shares": shares, "price": price,
                                 "value_usd": round(shares * price, 2)})
        if code == "P":
            buy_shares += shares
            buy_value += shares * price
        elif code == "S":
            sell_shares += shares
            sell_value += shares * price
        else:
            other[code] = other.get(code, 0.0) + shares

    period = _date(_text(root, "periodOfReport"))
    ordered = sorted(dates)
    return {
        "transaction_date": ordered[0] if ordered else period,
        "last_transaction_date": ordered[-1] if ordered else period,
        "transaction_dates": ordered,
        "period_of_report": period,
        "owner": _text(root, "reportingOwner/reportingOwnerId/rptOwnerName") or "Unknown insider",
        "role": role,
        "is_10b5_1": _text(root, "aff10b5One") in ("1", "true"),
        "buy_shares": buy_shares,
        "buy_value_usd": round(buy_value, 2),
        "sell_shares": sell_shares,
        "sell_value_usd": round(sell_value, 2),
        "other_codes": other,
        "transactions": transactions,
    }
