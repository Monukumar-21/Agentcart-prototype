"""
Policy engine — spending limits and rate limiting.

Decides whether a financial action (checkout, refund) should be auto-approved
or blocked for manual review.
"""

from __future__ import annotations
import os
import time
import threading
from collections import defaultdict
from app.schema import PolicyDecision

MAX_AUTO_APPROVE_RUPEES = float(os.getenv("MAX_AUTO_APPROVE_RUPEES", "2000.00"))
MAX_ACTIONS_PER_MINUTE = int(os.getenv("MAX_ACTIONS_PER_MINUTE", "5"))

_lock = threading.Lock()
_action_history: dict[str, list[float]] = defaultdict(list)


def get_settings() -> dict:
    with _lock:
        return {
            "max_auto_approve_rupees": MAX_AUTO_APPROVE_RUPEES,
            "max_actions_per_minute": MAX_ACTIONS_PER_MINUTE
        }


def update_settings(max_auto_approve_rupees: float, max_actions_per_minute: int) -> None:
    global MAX_AUTO_APPROVE_RUPEES, MAX_ACTIONS_PER_MINUTE
    with _lock:
        MAX_AUTO_APPROVE_RUPEES = max_auto_approve_rupees
        MAX_ACTIONS_PER_MINUTE = max_actions_per_minute


def _within_rate_limit(actor: str) -> bool:
    now = time.time()
    window = 60.0
    with _lock:
        history = [t for t in _action_history[actor] if now - t < window]
        history.append(now)
        _action_history[actor] = history
        return len(history) <= MAX_ACTIONS_PER_MINUTE


def evaluate(*, actor: str, tool: str, amount_rupees: float | None = None) -> PolicyDecision:
    if not _within_rate_limit(actor):
        return PolicyDecision(
            allowed=False,
            reason=f'Rate limit exceeded: more than {MAX_ACTIONS_PER_MINUTE} actions/minute for "{actor}"',
            rule="rate_limit",
        )

    if tool in ("checkout_cart", "refund_payment"):
        if amount_rupees is None or amount_rupees <= 0:
            return PolicyDecision(allowed=False, reason="Invalid or missing amount", rule="amount_required")

        if amount_rupees > MAX_AUTO_APPROVE_RUPEES:
            return PolicyDecision(
                allowed=False,
                reason=f"₹{amount_rupees:.2f} exceeds auto-approval limit of ₹{MAX_AUTO_APPROVE_RUPEES:.2f}",
                rule="max_auto_approve",
            )

    return PolicyDecision(allowed=True, reason="Within policy bounds")
