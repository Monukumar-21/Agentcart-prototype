"""
state_manager.py -- tracks the lifecycle of each transaction the
orchestrator creates (created -> pending_payment -> paid -> refund_pending
-> refunded), and supports suspending a transaction so it's excluded from
further automated processing (e.g. if something looks wrong mid-flow, a
merchant or the error/retry layer can freeze it without deleting history).
This is in-memory for the prototype; swap for Redis/Postgres in production.
"""

from __future__ import annotations
import threading
from typing import Optional
from app.schema import TransactionState

_lock = threading.Lock()
_transactions: dict[str, TransactionState] = {}


def create(order_id: str, *, sku: str, actor: str, amount_paise: int) -> TransactionState:
    with _lock:
        tx = TransactionState(
            order_id=order_id,
            sku=sku,
            actor=actor,
            status="created",
            amount_paise=amount_paise,
            history=["created"],
        )
        _transactions[order_id] = tx
        return tx


def transition(order_id: str, new_status: str) -> Optional[TransactionState]:
    with _lock:
        tx = _transactions.get(order_id)
        if tx is None:
            return None
        if tx.status == "suspended" and new_status != "suspended":
            # A suspended transaction stays excluded from further processing
            # until explicitly un-suspended -- not implemented as an
            # automated path on purpose, since resuming a frozen money
            # action should be a deliberate human decision.
            return tx
        tx.status = new_status
        tx.history.append(new_status)
        return tx


def suspend(order_id: str, reason: str) -> Optional[TransactionState]:
    with _lock:
        tx = _transactions.get(order_id)
        if tx is None:
            return None
        tx.status = "suspended"
        tx.history.append(f"suspended: {reason}")
        return tx


def get(order_id: str) -> Optional[TransactionState]:
    return _transactions.get(order_id)


def snapshot() -> list[TransactionState]:
    with _lock:
        return list(_transactions.values())
