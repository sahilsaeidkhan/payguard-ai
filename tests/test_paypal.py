"""Tests for the PayPal sandbox client — all mocked, no network/creds."""

import os

import httpx
import pytest
from fastapi.testclient import TestClient

from payguard.api import app
from payguard.paypal_client import (
    PayPalClient,
    PayPalError,
    PayPalNotConfigured,
    order_to_transaction,
)

client = TestClient(app)


def _mock_http():
    def handler(request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-test"})
        if request.url.path == "/v2/checkout/orders":
            return httpx.Response(
                201,
                json={
                    "id": "ORDER-123",
                    "status": "CREATED",
                    "links": [
                        {"rel": "approve", "href": "https://sandbox.paypal.com/checkoutnow?token=ORDER-123"}
                    ],
                },
            )
        return httpx.Response(404, json={})

    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api-m.sandbox.paypal.com")


def test_token_and_create_order_mocked(monkeypatch):
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "test-id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "test-secret")
    pp = PayPalClient(http=_mock_http())
    assert pp.get_access_token() == "tok-test"
    order = pp.create_order(400.0, "USD")
    assert order["id"] == "ORDER-123"
    assert order["status"] == "CREATED"
    assert "sandbox.paypal.com" in order["approve_url"]


def test_missing_credentials_raise(monkeypatch):
    monkeypatch.delenv("PAYPAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("PAYPAL_CLIENT_SECRET", raising=False)
    with pytest.raises(PayPalNotConfigured):
        PayPalClient(http=_mock_http()).get_access_token()


def test_order_to_transaction_mapping():
    txn = order_to_transaction(
        {
            "id": "ORDER-9",
            "purchase_units": [{"amount": {"currency_code": "EUR", "value": "250.00"}}],
            "payer": {"email_address": "buyer@example.com"},
        },
        seller_currency="USD",
    )
    assert txn["id"] == "ORDER-9"
    assert txn["amount"] == 250.0
    assert txn["currency_mismatch"] == 1
    assert txn["payer_email"] == "buyer@example.com"


def test_paypal_status_reports_unconfigured(monkeypatch):
    monkeypatch.delenv("PAYPAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("PAYPAL_CLIENT_SECRET", raising=False)
    resp = client.get("/paypal/status")
    assert resp.status_code == 200
    assert resp.json()["configured"] is False
    # The hint names the env vars (not their values) — that is setup help,
    # not a leak; just confirm no credential value appears.
    assert "test-secret" not in resp.text
    assert resp.json()["hint"] is not None


def test_paypal_order_without_credentials_is_503(monkeypatch):
    monkeypatch.delenv("PAYPAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("PAYPAL_CLIENT_SECRET", raising=False)
    resp = client.post("/paypal/order", json={"amount": 120, "currency": "USD"})
    assert resp.status_code == 503


def test_paypal_token_failure_raises(monkeypatch):
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "x")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "y")

    def handler(request):
        return httpx.Response(401, json={"error": "invalid_client"})

    pp = PayPalClient(
        http=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api-m.sandbox.paypal.com")
    )
    with pytest.raises(PayPalError):
        pp.get_access_token()
