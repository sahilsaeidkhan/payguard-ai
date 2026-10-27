"""PayGuard AI — AI payment-risk copilot for small sellers.

Pipeline: transaction -> numeric features -> XGBoost risk model ->
per-transaction explanation (top contributing factors) -> plain-language summary.

The explanation method is deliberately transparent and honest: for each
transaction we compare its feature values against the "safe seller baseline"
(medians of low-risk training transactions) and weight each deviation by the
model's global feature importance. The result is a ranked list of the factors
that pushed this transaction toward risk, in plain language. No black box.
"""

FEATURES = [
    "amount",
    "amount_vs_seller_avg",   # transaction amount / seller's average order value
    "buyer_account_age_days",
    "buyer_orders_30d",       # orders from this buyer in the last 30 days
    "seller_velocity_1h",     # seller's orders in the last hour
    "country_mismatch",       # billing country != shipping country (0/1)
    "currency_mismatch",      # payment currency != seller's usual currency (0/1)
    "hour_of_day",
    "is_digital_goods",       # 0/1
    "buyer_disputes_90d",     # buyer's disputes in the last 90 days
]

# Human-readable names and the direction that raises risk.
FACTOR_TEXT = {
    "amount": ("Order value", "high order value"),
    "amount_vs_seller_avg": ("Amount vs your average order", "amount well above your usual order value"),
    "buyer_account_age_days": ("Buyer account age", "very new buyer account"),
    "buyer_orders_30d": ("Buyer order history", "no recent orders from this buyer"),
    "seller_velocity_1h": ("Order velocity", "unusual burst of orders in the last hour"),
    "country_mismatch": ("Country mismatch", "billing and shipping countries differ"),
    "currency_mismatch": ("Currency mismatch", "payment currency differs from your usual currency"),
    "hour_of_day": ("Time of day", "order placed at an unusual hour"),
    "is_digital_goods": ("Digital goods", "instant-delivery digital goods"),
    "buyer_disputes_90d": ("Buyer dispute history", "buyer has recent disputes"),
}


def transaction_to_features(txn: dict) -> list:
    """Convert a raw transaction dict into the model's feature vector.

    Missing fields fall back to neutral (typical safe) values so a partial
    record can still be scored instead of crashing the queue.
    """
    avg = float(txn.get("seller_avg_order_value") or 50.0)
    amount = float(txn.get("amount") or 0.0)
    return [
        amount,
        amount / avg if avg else 0.0,
        float(txn.get("buyer_account_age_days", 365)),
        float(txn.get("buyer_orders_30d", 1)),
        float(txn.get("seller_velocity_1h", 1)),
        float(txn.get("country_mismatch", 0)),
        float(txn.get("currency_mismatch", 0)),
        float(txn.get("hour_of_day", 12)),
        float(txn.get("is_digital_goods", 0)),
        float(txn.get("buyer_disputes_90d", 0)),
    ]


def risk_band(score: float) -> str:
    if score >= 0.7:
        return "HIGH"
    if score >= 0.4:
        return "MEDIUM"
    return "LOW"


def recommended_action(score: float) -> str:
    if score >= 0.7:
        return "HOLD — review before shipping"
    if score >= 0.4:
        return "REVIEW — check buyer details before shipping"
    return "APPROVE — ship as normal"
