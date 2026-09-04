"""
policy_engine.py -- the single choke point that decides whether a money
action is *allowed to execute*, given a well-formed request that already
passed guardrails. This is where "bounded" lives: spending limits and rate
limits, in one place, configurable from .env.
"""

from __future__ import annotations
import os
import time
import threading
from collections import defaultdict
from app.schema import PolicyDecision

MAX_AUTO_APPROVE_PAISE = int(os.getenv("MAX_AUTO_APPROVE_PAISE", "200000"))
MAX_ACTIONS_PER_MINUTE = int(os.getenv("MAX_ACTIONS_PER_MINUTE", "5"))

_lock = threading.Lock()
_action_history: dict[str, list[float]] = defaultdict(list)


def _within_rate_limit(actor: str) -> bool:
    now = time.time()
    window = 60.0
    with _lock:
        history = [t for t in _action_history[actor] if now - t < window]
        history.append(now)
        _action_history[actor] = history
        return len(history) <= MAX_ACTIONS_PER_MINUTE


def evaluate(*, actor: str, tool: str, amount_paise: int | None = None) -> PolicyDecision:
    if not _within_rate_limit(actor):
        return PolicyDecision(
            allowed=False,
            reason=f'Rate limit exceeded: more than {MAX_ACTIONS_PER_MINUTE} money actions/minute for actor "{actor}"',
            rule="rate_limit",
        )

    if tool in ("create_checkout_order", "refund_payment"):
        if amount_paise is None or amount_paise <= 0:
            return PolicyDecision(allowed=False, reason="Invalid or missing amount", rule="amount_required")

        if amount_paise > MAX_AUTO_APPROVE_PAISE:
            return PolicyDecision(
                allowed=False,
                reason=(
                    f"Amount \u20b9{amount_paise/100:.2f} exceeds auto-approval limit of "
                    f"\u20b9{MAX_AUTO_APPROVE_PAISE/100:.2f} -- needs manual merchant approval"
                ),
                rule="max_auto_approve",
            )

    return PolicyDecision(allowed=True, reason="Within policy bounds")
