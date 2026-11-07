"""PayPal Developer Platform client (sandbox) for PayGuard AI.

This is the project's real PayPal integration, not a mock: with sandbox
credentials it talks to the PayPal Orders API — OAuth2 client-credentials
token, create order, get order, capture order. Without credentials it fails
loudly (PayPalNotConfigured) instead of pretending to work, so the demo
never shows fake PayPal data as real.

Setup (free, no KYC): create an app at developer.paypal.com (Sandbox),
then set:
    PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET
    PAYPAL_BASE_URL (optional, defaults to the sandbox API)

The API layer exposes this as POST /paypal/order, which creates a sandbox
order and immediately scores it with the XGBoost model — the end-to-end
loop the demo video shows: PayPal payment in, risk score + explanation out.
"""

import os

import httpx

SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"


class PayPalNotConfigured(Exception):
    """Raised when sandbox credentials are missing."""


class PayPalError(Exception):
    """Raised when the PayPal API returns an error."""


def _credentials():
    client_id = os.environ.get("PAYPAL_CLIENT_ID", "").strip()
    secret = os.environ.get("PAYPAL_CLIENT_SECRET", "").strip()
    if not client_id or not secret:
        raise PayPalNotConfigured(
            "Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET from a PayPal "
            "Developer sandbox app (developer.paypal.com) to enable the "
            "live sandbox demo."
        )
    return client_id, secret


def base_url() -> str:
    return os.environ.get("PAYPAL_BASE_URL", SANDBOX_BASE_URL).strip()


def is_configured() -> bool:
    return bool(
        os.environ.get("PAYPAL_CLIENT_ID", "").strip()
        and os.environ.get("PAYPAL_CLIENT_SECRET", "").strip()
    )


class PayPalClient:
    """Thin wrapper over the PayPal Orders API (sandbox by default).

    `http` is injectable so tests can pass an httpx.Client backed by a
    MockTransport — no network, no credentials needed for the test suite.
    """

    def __init__(self, http=None):
        self._http = http
        self._token = None

    def _client(self):
        if self._http:
            return self._http
        # Build the transport explicitly instead of trust_env=True:
        # httpx crashes parsing this host's NO_PROXY (bracketed IPv6
        # entries) at construction time. But a proxy may still be
        # required for egress, so pass HTTPS_PROXY through directly,
        # and honour SSL_CERT_FILE when the proxy TLS-intercepts with
        # a locally installed CA (system bundle instead of certifi).
        kwargs = {"base_url": base_url(), "timeout": 30.0, "trust_env": False}
        proxy = (
            os.environ.get("HTTPS_PROXY")
            or os.environ.get("https_proxy")
            or os.environ.get("HTTP_PROXY")
            or os.environ.get("http_proxy")
        )
        if proxy:
            kwargs["proxy"] = proxy
        if os.environ.get("SSL_CERT_FILE"):
            kwargs["verify"] = os.environ["SSL_CERT_FILE"]
        elif os.path.exists("/etc/ssl/certs/ca-certificates.crt"):
            kwargs["verify"] = "/etc/ssl/certs/ca-certificates.crt"
        return httpx.Client(**kwargs)

    def get_access_token(self) -> str:
        if self._token:
            return self._token
        client_id, secret = _credentials()
        resp = self._client().post(
            "/v1/oauth2/token",
            auth=(client_id, secret),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            raise PayPalError(f"PayPal token request failed: {resp.status_code}")
        self._token = resp.json()["access_token"]
        return self._token

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.get_access_token()}",
            "Content-Type": "application/json",
        }

    def create_order(self, amount: float, currency: str = "USD") -> dict:
        """Create a sandbox order; returns id, status, approve link."""
        # Headers first: _headers() raises PayPalNotConfigured before any
        # HTTP client is constructed (argument evaluation order would
        # otherwise build the client first).
        headers = self._headers()
        resp = self._client().post(
            "/v2/checkout/orders",
            headers=headers,
            json={
                "intent": "CAPTURE",
                "purchase_units": [
                    {"amount": {"currency_code": currency, "value": f"{amount:.2f}"}}
                ],
            },
        )
        if resp.status_code not in (200, 201):
            raise PayPalError(f"PayPal create-order failed: {resp.status_code}")
        data = resp.json()
        approve = next(
            (l["href"] for l in data.get("links", []) if l.get("rel") == "approve"),
            None,
        )
        return {"id": data["id"], "status": data.get("status"), "approve_url": approve}

    def get_order(self, order_id: str) -> dict:
        headers = self._headers()
        resp = self._client().get(f"/v2/checkout/orders/{order_id}", headers=headers)
        if resp.status_code != 200:
            raise PayPalError(f"PayPal get-order failed: {resp.status_code}")
        return resp.json()

    def capture_order(self, order_id: str) -> dict:
        headers = self._headers()
        resp = self._client().post(
            f"/v2/checkout/orders/{order_id}/capture", headers=headers, json={}
        )
        if resp.status_code not in (200, 201):
            raise PayPalError(f"PayPal capture failed: {resp.status_code}")
        return resp.json()


def order_to_transaction(order: dict, seller_avg_order_value: float = 55.0,
                         seller_currency: str = "USD") -> dict:
    """Map a PayPal order to a PayGuard transaction dict for scoring.

    Only fields PayPal actually returns are used. Buyer history fields the
    order does not carry (account age, disputes) fall back to the model's
    neutral defaults in transaction_to_features — the score is honest about
    being amount/mismatch-driven for a fresh sandbox order, and the
    explanation only lists factors the data supports.
    """
    unit = (order.get("purchase_units") or [{}])[0]
    amount_info = unit.get("amount", {})
    amount = float(amount_info.get("value", 0) or 0)
    currency = amount_info.get("currency_code", seller_currency)
    payer = order.get("payer", {})
    payer_country = (payer.get("address") or {}).get("country_code")
    ship_country = ((unit.get("shipping") or {}).get("address") or {}).get("country_code")
    country_mismatch = (
        1 if payer_country and ship_country and payer_country != ship_country else 0
    )
    return {
        "id": order.get("id", "PAYPAL-?"),
        "amount": amount,
        "seller_avg_order_value": seller_avg_order_value,
        "currency_mismatch": 1 if currency != seller_currency else 0,
        "country_mismatch": country_mismatch,
        "payer_email": payer.get("email_address"),
    }
