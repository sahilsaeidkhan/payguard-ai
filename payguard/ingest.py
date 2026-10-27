"""CSV ingestion for PayGuard AI.

A seller's second way to get transactions into PayGuard (besides the demo
queue and, from the Oct 31 round, the live PayPal sandbox feed): export or
paste a transaction CSV and score every row.

Accepted columns — the canonical names, plus the aliases a PayPal export or
a seller's own spreadsheet would use. Only `amount` is required; every other
column falls back to the neutral defaults in `transaction_to_features`, so a
partial export still scores instead of failing.
"""

import csv
import io

# canonical field -> accepted header spellings (lowercased, stripped)
COLUMN_ALIASES = {
    "id": ["id", "transaction_id", "txn_id", "order_id", "paypal_transaction_id"],
    "amount": ["amount", "gross_amount", "payment_amount", "total", "amount_usd",
               "gross", "value"],
    "seller_avg_order_value": ["seller_avg_order_value", "seller_average_order_value",
                               "avg_order_value", "average_order_value"],
    "buyer_account_age_days": ["buyer_account_age_days", "account_age_days",
                              "buyer_age_days", "payer_account_age_days"],
    "buyer_orders_30d": ["buyer_orders_30d", "buyer_orders_last_30d",
                         "orders_30d", "buyer_order_count"],
    "seller_velocity_1h": ["seller_velocity_1h", "orders_last_hour",
                           "velocity_1h"],
    "country_mismatch": ["country_mismatch", "billing_shipping_country_mismatch",
                         "country_differs"],
    "currency_mismatch": ["currency_mismatch", "currency_differs"],
    "hour_of_day": ["hour_of_day", "hour"],
    "is_digital_goods": ["is_digital_goods", "digital_goods", "is_digital"],
    "buyer_disputes_90d": ["buyer_disputes_90d", "disputes_90d",
                           "buyer_disputes"],
    "buyer": ["buyer", "buyer_email", "payer_email", "payer"],
}

_INT_FIELDS = {"buyer_account_age_days", "buyer_orders_30d", "seller_velocity_1h",
               "country_mismatch", "currency_mismatch", "hour_of_day",
               "is_digital_goods", "buyer_disputes_90d"}


def _header_map(fieldnames):
    """Map each canonical field to the actual header present in the file."""
    lookup = {}
    for raw in fieldnames or []:
        lookup[raw.strip().lower()] = raw
    mapping = {}
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lookup:
                mapping[field] = lookup[alias]
                break
    return mapping


def parse_transactions_csv(text: str) -> list:
    """Parse CSV text into raw transaction dicts ready for scoring.

    Raises ValueError naming the row when a row has no usable amount, or
    when the file has no amount column at all. Blank rows are skipped.
    """
    reader = csv.DictReader(io.StringIO(text))
    mapping = _header_map(reader.fieldnames)
    if "amount" not in mapping:
        raise ValueError(
            "CSV has no amount column (accepted: "
            + ", ".join(COLUMN_ALIASES["amount"]) + ")"
        )
    txns = []
    for i, row in enumerate(reader, start=2):  # row 1 is the header
        if row is None or all((v is None or str(v).strip() == "") for v in row.values()):
            continue
        raw_amount = (row.get(mapping["amount"]) or "").strip()
        try:
            amount = float(raw_amount)
        except (TypeError, ValueError):
            raise ValueError(f"Row {i}: amount {raw_amount!r} is not a number")
        if amount <= 0:
            raise ValueError(f"Row {i}: amount must be positive, got {amount}")
        txn = {"id": f"CSV-{i - 1}", "amount": amount}
        for field, header in mapping.items():
            if field in ("id", "amount"):
                continue
            raw = row.get(header)
            if raw is None or str(raw).strip() == "":
                continue
            if field in ("buyer",):
                txn[field] = str(raw).strip()
            elif field in _INT_FIELDS:
                try:
                    txn[field] = int(float(raw))
                except ValueError:
                    raise ValueError(f"Row {i}: {field} value {raw!r} is not a number")
            else:
                try:
                    txn[field] = float(raw)
                except ValueError:
                    raise ValueError(f"Row {i}: {field} value {raw!r} is not a number")
        id_header = mapping.get("id")
        if id_header and row.get(id_header):
            txn["id"] = str(row[id_header]).strip()
        txns.append(txn)
    if not txns:
        raise ValueError("CSV contains no data rows")
    return txns


def sample_csv() -> str:
    """A small example CSV (same shape as the demo queue) for sellers to try."""
    from .data import sample_transactions

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["transaction_id", "amount", "buyer_account_age_days",
                     "buyer_orders_30d", "country_mismatch",
                     "buyer_disputes_90d", "buyer_email"])
    for t in sample_transactions(n=6):
        writer.writerow([t["id"], t["amount"], t["buyer_account_age_days"],
                         t["buyer_orders_30d"], t["country_mismatch"],
                         t["buyer_disputes_90d"], t["buyer"]])
    return buf.getvalue()
