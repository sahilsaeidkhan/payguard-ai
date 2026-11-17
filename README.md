# PayGuard AI

AI payment-risk copilot for small sellers. Built for the PayPal AI Hackathon 2026.

A small seller usually ships the order first and finds out later whether the payment was risky. PayGuard tries to flip that order. It scores each incoming payment before shipping, explains the score in plain language, and puts the payment in a queue where the seller records what they decided: HOLD, REVIEW or APPROVE.

## Why this matters

A chargeback costs more than the sale itself. Mastercard and Javelin (2026) put third-party fees plus internal handling at an average of $128 per chargeback, before counting the lost sale and the shipped goods. LexisNexis (2026) puts the total fraud cost at $3.75 for every $1 of direct loss in US retail and ecommerce. Once a risky order is shipped, most of that cost is already locked in. Before shipping, prevention is still possible.

Sources: Mastercard/Javelin figures via https://www.chargeflow.io/blog/what-is-the-true-cost-of-chargebacks-to-your-business and LexisNexis figure via https://www.chargebackstop.com/blog/chargeback-statistics

## How it works

1. Payments come in three ways: the built-in demo queue, a CSV upload, or a live PayPal sandbox order created through the PayPal Orders API.
2. An XGBoost model scores each payment using features like the amount compared to the seller's usual order value, buyer account age, order velocity, country and currency mismatch, a digital-goods flag, and the buyer's dispute history.
3. The explanation is measured from the model itself. Each feature is replaced one at a time with a safe baseline value, and the drop in the risk score is that feature's contribution. So the seller sees something like: "High risk: new buyer account, amount well above your usual order value, billing and shipping countries differ."
4. The seller works through a Streamlit dashboard queue and records a decision for each payment. Decisions are saved to a log that survives API restarts and can be exported as CSV.

## Results

- Accuracy 0.945 and ROC-AUC 0.9895 on held-out data.
- 50 automated tests, all passing.
- The live sandbox loop is verified end to end: a real sandbox order was created through the Orders API and scored by the model (order id 3S06808W3386635N).

One honest note: the training data is synthetic. Real seller payments cannot be used in a demo, so the data is generated from documented rules (see `payguard/data.py`). That makes the metrics higher than they would be on real data. Treat the score as a decision aid, not a guarantee.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python train.py            # trains the XGBoost model, prints metrics
python -m pytest tests/ -q # tests (model + API)

uvicorn payguard.api:app --reload        # API at http://127.0.0.1:8000/docs
streamlit run payguard/dashboard.py      # dashboard
```

## API

- `GET /health` — status and model metrics
- `POST /score` — score one transaction. Inputs are validated, so a bad payload gets a clear 422 instead of a nonsense score
- `GET /transactions` — the scored demo queue
- `GET /model` — features, importances, metrics
- `POST /upload-csv` — score every row of an uploaded CSV, riskiest first. Only an `amount` column is required; PayPal-export headers like `gross_amount` and `transaction_id` are accepted
- `GET /sample-csv` — an example CSV in the accepted format
- `POST /decisions` — record a HOLD / REVIEW / APPROVE decision on a payment
- `GET /decisions` — decision log and counts by decision
- `GET /decisions/export` — the decision log as a CSV download
- `GET /paypal/status` — sandbox wiring status (never exposes credentials)
- `POST /paypal/order` — create a live PayPal sandbox order and score it (returns the order id, status, buyer-approval URL, and the risk score)

Example:

```bash
curl -X POST http://127.0.0.1:8000/score \
  -H 'Content-Type: application/json' \
  -d '{"amount": 400, "seller_avg_order_value": 55,
       "buyer_account_age_days": 2, "country_mismatch": 1,
       "buyer_disputes_90d": 2}'
```

## PayPal sandbox setup

Free, and no KYC needed:

1. Create an app at [developer.paypal.com](https://developer.paypal.com) (Sandbox) and copy its Client ID and Secret.
2. `export PAYPAL_CLIENT_ID=... PAYPAL_CLIENT_SECRET=...`
3. Start the API, then `POST /paypal/order` with an amount. You get a sandbox order id, an approval URL, and a risk score.

Without the credentials, `/paypal/status` reports `configured: false` and `/paypal/order` returns 503 with setup instructions. It never falls back to fake data.

## Project status

Built between 26 Oct and 5 Nov 2026 in twelve tagged versions (git tags `saved-v1` to `saved-v12` hold the step-by-step history). Submitted to the PayPal AI Hackathon on Devpost with a 99.8-second demo video recorded from the real dashboard, no mockups.

What is not there, deliberately: no live-money mode, and the model has never seen real transaction data. Both are the right call for a hackathon demo, and both would be the first things to change in a real product.
