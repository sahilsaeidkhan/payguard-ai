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

api_base = st.text_input("API base URL", "http://127.0.0.1:8000")
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
        st.write("**Your decision:**")
        b1, b2, b3 = st.columns(3)
        for col, choice in ((b1, "HOLD"), (b2, "REVIEW"), (b3, "APPROVE")):
            if col.button(choice, key=f"{choice}-{r['id']}"):
                try:
                    import httpx

                    resp = httpx.post(
                        f"{api_base}/decisions",
                        json={
                            "txn_id": r["id"],
                            "decision": choice,
                            "risk_band": r["risk_band"],
                            "risk_score": r["risk_score"],
                            "amount": r["amount"],
                        },
                        timeout=5.0,
                    )
                    if resp.status_code == 201:
                        st.success(f"Recorded {choice} for {r['id']}.")
                    else:
                        st.error(f"Could not record decision: {resp.text}")
                except Exception as e:
                    st.warning(
                        f"API not reachable at {api_base} — start it with "
                        f"uvicorn first, then retry: {e}"
                    )

st.divider()
st.subheader("Decision log")
st.write(
    "Decisions you recorded this session (held payments stay held until "
    "you change them). The log lives in the API's memory and resets when "
    "the API restarts."
)
if st.button("Refresh decision log"):
    st.rerun()
try:
    import httpx

    log = httpx.get(f"{api_base}/decisions", timeout=5.0).json()
    st.write(
        f"{log['summary']['total']} decisions — "
        + ", ".join(
            f"{k}: {v}" for k, v in log["summary"]["by_decision"].items()
        )
    )
    if log["decisions"]:
        st.table(
            [
                {
                    "Payment": d["txn_id"],
                    "Decision": d["decision"],
                    "Risk": d["risk_band"],
                    "Amount": f"${d['amount']:.2f}" if d["amount"] else "—",
                    "When": d["decided_at"][:19],
                }
                for d in log["decisions"]
            ]
        )
except Exception:
    st.write("Decision log unavailable — start the API with uvicorn first.")

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
st.subheader("Live PayPal sandbox demo")
st.write(
    "With `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` set (free sandbox app "
    "at developer.paypal.com), the API creates a real sandbox order and "
    "scores it: `POST /paypal/order`. Check the API's wiring status below."
)
if st.button("Check PayPal sandbox status"):
    try:
        import httpx

        status = httpx.get(f"{api_base}/paypal/status", timeout=5.0).json()
        if status["configured"]:
            st.success("PayPal sandbox is configured — create an order below.")
        else:
            st.warning(status["hint"])
    except Exception as e:
        st.warning(f"API not reachable at {api_base} (start it with uvicorn first): {e}")

st.write(
    "Create a real sandbox order and watch it get scored — the end-to-end "
    "loop (payment in, explanation out). Needs the sandbox credentials above; "
    "without them the API answers honestly instead of faking an order."
)
with st.form("paypal_demo"):
    demo_amount = st.number_input("Sandbox order amount ($)", min_value=1.0, value=120.0)
    demo_submitted = st.form_submit_button("Create + score sandbox order")
if demo_submitted:
    try:
        import httpx

        resp = httpx.post(
            f"{api_base}/paypal/order",
            json={"amount": demo_amount, "currency": "USD"},
            timeout=30.0,
        )
        if resp.status_code == 200:
            payload = resp.json()
            order, scored = payload["order"], payload["scored"]
            st.success(
                f"Order {order['id']} ({order['status']}) scored "
                f"{scored['risk_band']} ({scored['risk_score']:.0%}) — "
                f"{scored['action']}"
            )
            st.write(scored["summary"])
            if order.get("approve_url"):
                st.write(f"Buyer approval URL: {order['approve_url']}")
        elif resp.status_code == 503:
            st.warning(resp.json().get("detail", "PayPal sandbox not configured."))
        else:
            st.error(f"PayPal demo failed ({resp.status_code}): {resp.text}")
    except Exception as e:
        st.warning(f"API not reachable at {api_base} (start it with uvicorn first): {e}")

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
