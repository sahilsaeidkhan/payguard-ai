"""Streamlit dashboard for PayGuard AI — the seller's risk queue."""

import streamlit as st

from payguard.data import sample_transactions
from payguard.model import score_transaction

st.set_page_config(page_title="PayGuard AI", page_icon="🛡️")
st.title("🛡️ PayGuard AI — payment-risk copilot")
st.write(
    "Every incoming payment is scored for fraud / dispute risk by an XGBoost "
    "model, with the reasons in plain language — so you decide before you ship."
)

if st.button("Refresh risk queue"):
    st.rerun()

results = [score_transaction(t) for t in sample_transactions()]
results.sort(key=lambda r: r["risk_score"], reverse=True)

high = sum(1 for r in results if r["risk_band"] == "HIGH")
medium = sum(1 for r in results if r["risk_band"] == "MEDIUM")
c1, c2, c3 = st.columns(3)
c1.metric("Payments in queue", len(results))
c2.metric("High risk — hold", high)
c3.metric("Medium risk — review", medium)

for r in results:
    emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}[r["risk_band"]]
    with st.expander(
        f"{emoji} {r['id']} — ${r['amount']:.2f} — {r['risk_band']} "
        f"({r['risk_score']:.0%}) — {r['action']}"
    ):
        st.write(r["summary"])
        if r["factors"]:
            st.write("**Top risk factors:**")
            for f in r["factors"]:
                st.write(f"- {f['factor']}: {f['detail']}")

st.divider()
st.subheader("Score your own transactions (CSV upload)")
st.write(
    "Upload a CSV of your payments — only an `amount` column is required; "
    "extra columns (buyer account age, country mismatch, disputes, …) sharpen "
    "the score. PayPal-export style headers like `gross_amount` work too."
)
from payguard.ingest import parse_transactions_csv, sample_csv

st.download_button("Download a sample CSV", sample_csv(), "sample_transactions.csv", "text/csv")
uploaded = st.file_uploader("Upload transaction CSV", type=["csv"])
if uploaded is not None:
    try:
        rows = parse_transactions_csv(uploaded.getvalue().decode("utf-8-sig"))
        scored = sorted(
            (score_transaction(t) for t in rows),
            key=lambda r: r["risk_score"], reverse=True,
        )
        st.success(f"Scored {len(scored)} transactions — riskiest first.")
        st.table(
            [
                {
                    "ID": r["id"],
                    "Amount": f"${r['amount']:.2f}",
                    "Risk": f"{r['risk_band']} ({r['risk_score']:.0%})",
                    "Action": r["action"],
                }
                for r in scored
            ]
        )
        for r in scored:
            if r["risk_band"] != "LOW":
                st.write(f"**{r['id']}** — {r['summary']}")
    except ValueError as e:
        st.error(f"Could not read that CSV: {e}")

st.divider()
st.subheader("Score a single payment")
with st.form("score_one"):
    amount = st.number_input("Order amount ($)", min_value=1.0, value=120.0)
    age = st.number_input("Buyer account age (days)", min_value=0, value=5)
    mismatch = st.checkbox("Billing country ≠ shipping country")
    disputes = st.number_input("Buyer disputes (90 days)", min_value=0, value=0)
    submitted = st.form_submit_button("Score it")
if submitted:
    r = score_transaction(
        {
            "id": "MANUAL-1",
            "amount": amount,
            "buyer_account_age_days": age,
            "country_mismatch": int(mismatch),
            "buyer_disputes_90d": disputes,
        }
    )
    st.write(f"**{r['risk_band']} — {r['risk_score']:.0%}** — {r['action']}")
    st.write(r["summary"])
