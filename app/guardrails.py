"""
Guardrails — validates requests before they reach the policy engine.

Checks: actor blocklists, SKU validity, stock availability, quantity limits,
refund ceiling. If any check fails, the request gets blocked with a reason.
"""

from __future__ import annotations
from app.schema import GuardrailResult
from app import recommendation_engine as catalog

import threading

_lock = threading.Lock()
BLOCKED_ACTORS: set[str] = set()

MAX_QTY_PER_ORDER = 10
MAX_REFUND_RUPEES_ABSOLUTE = 10_000.00


def get_settings() -> dict:
    with _lock:
        return {
            "max_qty_per_order": MAX_QTY_PER_ORDER,
            "blocked_actors": list(BLOCKED_ACTORS)
        }


def update_settings(max_qty_per_order: int, blocked_actors: list[str]) -> None:
    global MAX_QTY_PER_ORDER, BLOCKED_ACTORS
    with _lock:
        MAX_QTY_PER_ORDER = max_qty_per_order
        BLOCKED_ACTORS = set(blocked_actors)


def check_actor(actor: str) -> GuardrailResult:
    if not actor or not actor.strip():
        return GuardrailResult(passed=False, reason="Missing actor identity", rule="actor_required")
    with _lock:
        if actor in BLOCKED_ACTORS:
            return GuardrailResult(passed=False, reason=f'Actor "{actor}" is blocklisted', rule="actor_blocklist")
    return GuardrailResult(passed=True, reason="Actor identity present and not blocklisted")


def check_add_to_cart(actor: str, sku: str, qty: int) -> GuardrailResult:
    actor_check = check_actor(actor)
    if not actor_check.passed:
        return actor_check

    item = catalog.find_by_sku(sku)
    if item is None:
        return GuardrailResult(passed=False, reason=f'Unknown SKU "{sku}"', rule="sku_exists")

    if qty <= 0:
        return GuardrailResult(passed=False, reason="Quantity must be positive", rule="positive_qty")

    if item.stock < qty:
        return GuardrailResult(
            passed=False, reason=f'Insufficient stock for "{sku}": {item.stock} available', rule="stock_available"
        )

    return GuardrailResult(passed=True, reason="Add to cart request well-formed")


def check_cart_checkout(actor: str, cart_items: dict[str, int]) -> GuardrailResult:
    actor_check = check_actor(actor)
    if not actor_check.passed:
        return actor_check

    if not cart_items:
        return GuardrailResult(passed=False, reason="Cart is empty", rule="cart_not_empty")

    with _lock:
        max_qty = MAX_QTY_PER_ORDER

    total_qty = sum(cart_items.values())
    if total_qty > max_qty:
        return GuardrailResult(
            passed=False,
            reason=f"Total cart quantity {total_qty} exceeds per-order limit of {max_qty}",
            rule="max_qty_per_order",
        )

    for sku, qty in cart_items.items():
        item = catalog.find_by_sku(sku)
        if item is None:
            return GuardrailResult(passed=False, reason=f'Unknown SKU "{sku}" in cart', rule="sku_exists")
        if item.stock < qty:
            return GuardrailResult(
                passed=False, reason=f'Insufficient stock for "{sku}": {item.stock} available', rule="stock_available"
            )

    return GuardrailResult(passed=True, reason="Checkout request well-formed")


def check_refund(actor: str, payment_id: str, amount_rupees: float) -> GuardrailResult:
    actor_check = check_actor(actor)
    if not actor_check.passed:
        return actor_check

    if not payment_id or not payment_id.strip():
        return GuardrailResult(passed=False, reason="Missing payment_id", rule="payment_id_required")

    if amount_rupees > MAX_REFUND_RUPEES_ABSOLUTE:
        return GuardrailResult(
            passed=False,
            reason=(
                f"Refund ₹{amount_rupees:.2f} exceeds absolute ceiling of "
                f"₹{MAX_REFUND_RUPEES_ABSOLUTE:.2f}"
            ),
            rule="absolute_refund_ceiling",
        )

    return GuardrailResult(passed=True, reason="Refund request well-formed")
