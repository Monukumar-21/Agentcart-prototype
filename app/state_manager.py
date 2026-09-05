"""
Transaction state manager.

Tracks the lifecycle of an order (created, pending, paid, etc.) in memory.
Allows for suspending transactions if something fails midway (like a refund).
"""

from __future__ import annotations
import threading
from typing import Optional
from app.schema import TransactionState

_lock = threading.Lock()
_transactions: dict[str, TransactionState] = {}


def create(order_id: str, *, items: dict[str, int], actor: str, amount_rupees: float) -> TransactionState:
    with _lock:
        tx = TransactionState(
            order_id=order_id,
            items=items,
            actor=actor,
            status="created",
            amount_rupees=amount_rupees,
            history=["created"],
        )
        _transactions[order_id] = tx
        return tx


def transition(order_id: str, new_status: str) -> Optional[TransactionState]:
    with _lock:
        tx = _transactions.get(order_id)
        if tx is None:
            return None
        # if a transaction is suspended, it needs manual intervention, so block transitions
        if tx.status == "suspended" and new_status != "suspended":
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
