"""
razorpay_client.py -- thin wrapper around the Razorpay Python SDK, with a
mock fallback so the whole app runs and is fully testable with zero
Razorpay signup. Set MOCK_MODE=false and real test-mode keys in .env to
switch to live Razorpay test-mode calls -- no other code changes needed,
since the mock mirrors the real client's method shapes.
"""

from __future__ import annotations
import os
import random
import secrets
import hmac
import hashlib
import time
from typing import Any

MOCK_MODE = os.getenv("MOCK_MODE", "true").lower() == "true" or not (
    os.getenv("RAZORPAY_KEY_ID") and os.getenv("RAZORPAY_KEY_SECRET")
)
MOCK_FAILURE_RATE = float(os.getenv("MOCK_FAILURE_RATE", "0.0"))


def _fake_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


class MockOrders:
    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        if random.random() < MOCK_FAILURE_RATE:
            raise RuntimeError("Simulated Razorpay timeout")
        return {
            "id": _fake_id("order"),
            "entity": "order",
            "amount": data["amount"],
            "currency": data.get("currency", "INR"),
            "receipt": data.get("receipt"),
            "status": "created",
            "notes": data.get("notes", {}),
            "created_at": int(time.time()),
        }


class MockPayments:
    def fetch(self, payment_id: str) -> dict[str, Any]:
        return {"id": payment_id, "entity": "payment", "status": "captured", "amount": 0}

    def refund(self, payment_id: str, data: dict[str, Any]) -> dict[str, Any]:
        if random.random() < MOCK_FAILURE_RATE:
            raise RuntimeError("Simulated Razorpay timeout")
        return {
            "id": _fake_id("rfnd"),
            "entity": "refund",
            "payment_id": payment_id,
            "amount": data["amount"],
            "status": "processed",
            "notes": data.get("notes", {}),
        }


class MockClient:
    def __init__(self) -> None:
        self.order = MockOrders()
        self.payment = MockPayments()


def _build_client():
    if MOCK_MODE:
        return MockClient()
    import razorpay  # imported lazily so mock mode never requires the real SDK config

    client = razorpay.Client(auth=(os.environ["RAZORPAY_KEY_ID"], os.environ["RAZORPAY_KEY_SECRET"]))
    return client


client = _build_client()


def create_order(*, amount_paise: int, receipt: str, notes: dict) -> dict[str, Any]:
    if MOCK_MODE:
        return client.order.create({"amount": amount_paise, "currency": "INR", "receipt": receipt, "notes": notes})
    return client.order.create({"amount": amount_paise, "currency": "INR", "receipt": receipt, "notes": notes})


def refund_payment(*, payment_id: str, amount_paise: int, notes: dict) -> dict[str, Any]:
    if MOCK_MODE:
        return client.payment.refund(payment_id, {"amount": amount_paise, "notes": notes})
    return client.payment.refund(payment_id, {"amount": amount_paise, "notes": notes})


def verify_signature(*, order_id: str, payment_id: str, signature: str) -> bool:
    if MOCK_MODE:
        return True
    body = f"{order_id}|{payment_id}"
    expected = hmac.new(
        os.environ["RAZORPAY_KEY_SECRET"].encode(), body.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
