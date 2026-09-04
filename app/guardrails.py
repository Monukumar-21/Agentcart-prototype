"""
guardrails.py -- the first line of defense, before anything reaches the
policy engine. Guardrails answer "is this request even well-formed and
sane", not "is this actor allowed to spend this much" (that's the policy
engine's job). Keeping them separate means each has one job and one place
to change: tighten spending rules in policy_engine.py, tighten what counts
as a sane request here.
"""

from __future__ import annotations
from app.schema import GuardrailResult
from app import catalog

# Actors that are hard-blocked regardless of policy (e.g. known-bad agents
# flagged by a merchant). Empty by default; a merchant would populate this.
BLOCKED_ACTORS: set[str] = set()

MAX_QTY_PER_ORDER = 10
MAX_REFUND_PAISE_ABSOLUTE = 10_000_00  # ₹10,000 -- a hard ceiling no policy override can exceed


def check_actor(actor: str) -> GuardrailResult:
    if not actor or not actor.strip():
        return GuardrailResult(passed=False, reason="Missing actor identity", rule="actor_required")
    if actor in BLOCKED_ACTORS:
        return GuardrailResult(passed=False, reason=f'Actor "{actor}" is blocklisted', rule="actor_blocklist")
    return GuardrailResult(passed=True, reason="Actor identity present and not blocklisted")


def check_checkout(actor: str, sku: str, qty: int) -> GuardrailResult:
    actor_check = check_actor(actor)
    if not actor_check.passed:
        return actor_check

    item = catalog.find_by_sku(sku)
    if item is None:
        return GuardrailResult(passed=False, reason=f'Unknown SKU "{sku}"', rule="sku_exists")

    if qty > MAX_QTY_PER_ORDER:
        return GuardrailResult(
            passed=False,
            reason=f"Quantity {qty} exceeds per-order guardrail of {MAX_QTY_PER_ORDER}",
            rule="max_qty_per_order",
        )

    if item.stock < qty:
        return GuardrailResult(
            passed=False, reason=f'Insufficient stock for "{sku}": {item.stock} available', rule="stock_available"
        )

    return GuardrailResult(passed=True, reason="Checkout request well-formed")


def check_refund(actor: str, payment_id: str, amount_paise: int) -> GuardrailResult:
    actor_check = check_actor(actor)
    if not actor_check.passed:
        return actor_check

    if not payment_id or not payment_id.strip():
        return GuardrailResult(passed=False, reason="Missing payment_id", rule="payment_id_required")

    if amount_paise > MAX_REFUND_PAISE_ABSOLUTE:
        return GuardrailResult(
            passed=False,
            reason=(
                f"Refund amount \u20b9{amount_paise/100:.2f} exceeds the absolute guardrail ceiling of "
                f"\u20b9{MAX_REFUND_PAISE_ABSOLUTE/100:.2f} -- no policy override can approve this"
            ),
            rule="absolute_refund_ceiling",
        )

    return GuardrailResult(passed=True, reason="Refund request well-formed")
