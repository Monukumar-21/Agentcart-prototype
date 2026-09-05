"""
Razorpay client wrapper with a mock fallback mode.

When MOCK_MODE is true, it simulates order creation, signature verification,
and refunds without needing real Razorpay credentials. 

Useful for testing the failure paths: set MOCK_FAILURE_RATE in the .env 
to randomly fail requests and see how the orchestrator handles retries.
"""

import os
import random
import uuid
import time
from typing import Any

MOCK_MODE = os.getenv("MOCK_MODE", "true").lower() == "true" or not (
    os.getenv("RAZORPAY_KEY_ID") and os.getenv("RAZORPAY_KEY_SECRET")
)
MOCK_FAILURE_RATE = float(os.getenv("MOCK_FAILURE_RATE", "0.0"))

if not MOCK_MODE:
    import razorpay
    # the razorpay library still uses pkg_resources which throws warnings on newer setups
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    
    client = razorpay.Client(
        auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET"))
    )


def _simulate_failure() -> None:
    """Randomly fail to test the retry mechanism."""
    if MOCK_FAILURE_RATE > 0 and random.random() < MOCK_FAILURE_RATE:
        raise RuntimeError("Mock network failure")


def create_order(amount_paise: int, receipt: str, notes: dict[str, Any]) -> dict[str, Any]:
    if MOCK_MODE:
        _simulate_failure()
        return {
            "id": f"order_mock_{uuid.uuid4().hex[:8]}",
            "entity": "order",
            "amount": amount_paise,
            "amount_paid": 0,
            "amount_due": amount_paise,
            "currency": "INR",
            "receipt": receipt,
            "status": "created",
            "attempts": 0,
            "notes": notes,
            "created_at": int(time.time()),
        }
    else:
        return client.order.create(
            {
                "amount": amount_paise,
                "currency": "INR",
                "receipt": receipt,
                "notes": notes,
            }
        )


def verify_signature(order_id: str, payment_id: str, signature: str) -> bool:
    if MOCK_MODE:
        _simulate_failure()
        # in mock mode, any signature passes
        return True
    else:
        try:
            client.utility.verify_payment_signature(
                {
                    "razorpay_order_id": order_id,
                    "razorpay_payment_id": payment_id,
                    "razorpay_signature": signature,
                }
            )
            return True
        except Exception:
            return False


def create_refund(payment_id: str, amount_paise: int) -> dict[str, Any]:
    if MOCK_MODE:
        _simulate_failure()
        return {
            "id": f"rfnd_mock_{uuid.uuid4().hex[:8]}",
            "entity": "refund",
            "amount": amount_paise,
            "currency": "INR",
            "payment_id": payment_id,
            "status": "processed",
            "speed_processed": "normal",
            "created_at": int(time.time()),
        }
    else:
        return client.payment.refund(
            payment_id,
            {"amount": amount_paise, "speed": "normal"}
        )


def fetch_order_payments(order_id: str, mock_paid: bool = True) -> list[dict[str, Any]]:
    """
    Fetch all payments for a given order from Razorpay.
    Used by the reconciliation agent to check if a 'created' order
    was actually paid (e.g. user paid but verification callback was lost
    due to a network timeout).

    In mock mode, simulates a captured payment if mock_paid=True.
    """
    if MOCK_MODE:
        _simulate_failure()
        if mock_paid:
            return [{
                "id": f"pay_mock_{uuid.uuid4().hex[:8]}",
                "entity": "payment",
                "amount": 0,  # amount is not used during reconciliation
                "currency": "INR",
                "status": "captured",
                "order_id": order_id,
                "method": "upi",
                "description": "Mock payment (simulated for reconciliation)",
                "created_at": int(time.time()),
            }]
        else:
            return []
    else:
        resp = client.order.payments(order_id)
        items = resp.get("items", resp) if isinstance(resp, dict) else resp
        return items if isinstance(items, list) else []
