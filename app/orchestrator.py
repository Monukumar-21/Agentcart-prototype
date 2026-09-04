
from __future__ import annotations
import time
from typing import Any

from app import catalog, guardrails, policy_engine, state_manager, razorpay_client
from app.audits import audit_logger
from app.retry import call_with_retry, RazorpayCallFailed
from app.schema import ToolResult

ACTOR_DEFAULT = "unspecified-agent"


def get_catalog(actor: str = ACTOR_DEFAULT) -> ToolResult:
    items = [i.model_dump() for i in catalog.get_catalog()]
    entry = audit_logger.log(actor=actor, tool="get_catalog", params={}, decision="allowed", reason="Read-only")
    return ToolResult(blocked=False, data={"catalog": items}, entry=entry)


def create_checkout_order(actor: str, sku: str, qty: int = 1) -> ToolResult:
    g = guardrails.check_checkout(actor, sku, qty)
    if not g.passed:
        entry = audit_logger.log(
            actor=actor, tool="create_checkout_order", params={"sku": sku, "qty": qty},
            decision="blocked", reason=g.reason,
        )
        return ToolResult(blocked=True, entry=entry)

    item = catalog.find_by_sku(sku)
    amount_paise = item.price_paise * qty

    decision = policy_engine.evaluate(actor=actor, tool="create_checkout_order", amount_paise=amount_paise)
    if not decision.allowed:
        entry = audit_logger.log(
            actor=actor, tool="create_checkout_order", params={"sku": sku, "qty": qty, "amount_paise": amount_paise},
            decision="blocked", reason=decision.reason,
        )
        return ToolResult(blocked=True, entry=entry)

    try:
        order = call_with_retry(
            lambda: razorpay_client.create_order(
                amount_paise=amount_paise, receipt=f"agentcart_{int(time.time()*1000)}",
                notes={"actor": actor, "sku": sku, "qty": qty},
            ),
            tool="create_checkout_order", actor=actor, params={"sku": sku, "qty": qty},
        )
    except RazorpayCallFailed as exc:
        entry = audit_logger.log(
            actor=actor, tool="create_checkout_order", params={"sku": sku, "qty": qty, "amount_paise": amount_paise},
            decision="blocked", reason=f"Razorpay unavailable after retries: {exc}",
        )
        return ToolResult(blocked=True, entry=entry)

    catalog.decrement_stock(sku, qty)
    state_manager.create(order["id"], sku=sku, actor=actor, amount_paise=amount_paise)
    state_manager.transition(order["id"], "pending_payment")

    import os
    base_url = os.getenv("BASE_URL", "http://localhost:8000")
    
    entry = audit_logger.log(
        actor=actor, tool="create_checkout_order", params={"sku": sku, "qty": qty, "amount_paise": amount_paise},
        decision="allowed", reason=decision.reason,
        result={"order_id": order["id"], "status": order["status"]},
    )
    return ToolResult(blocked=False, data={"order": order, "payment_link": f"{base_url}/pay/{order['id']}"}, entry=entry)


def verify_payment(actor: str, order_id: str, payment_id: str, signature: str) -> ToolResult:
    ok = razorpay_client.verify_signature(order_id=order_id, payment_id=payment_id, signature=signature)
    entry = audit_logger.log(
        actor=actor, tool="verify_payment", params={"order_id": order_id, "payment_id": payment_id},
        decision="allowed" if ok else "blocked",
        reason="Signature valid" if ok else "Signature verification failed",
    )
    if ok:
        state_manager.transition(order_id, "paid")
    return ToolResult(blocked=not ok, data={"verified": ok}, entry=entry)


def suggest_upsell(actor: str, sku: str) -> ToolResult:
    item = catalog.find_by_sku(sku)
    suggestion = catalog.find_by_sku(item.upsell_sku) if item and item.upsell_sku else None
    entry = audit_logger.log(
        actor=actor, tool="suggest_upsell", params={"sku": sku}, decision="allowed",
        reason="Read-only recommendation",
        result={"suggested_sku": suggestion.sku if suggestion else None},
    )
    return ToolResult(blocked=False, data={"suggestion": suggestion.model_dump() if suggestion else None}, entry=entry)


def refund_payment(actor: str, payment_id: str, amount_paise: int) -> ToolResult:
    g = guardrails.check_refund(actor, payment_id, amount_paise)
    if not g.passed:
        entry = audit_logger.log(
            actor=actor, tool="refund_payment", params={"payment_id": payment_id, "amount_paise": amount_paise},
            decision="blocked", reason=g.reason,
        )
        return ToolResult(blocked=True, entry=entry)

    decision = policy_engine.evaluate(actor=actor, tool="refund_payment", amount_paise=amount_paise)
    if not decision.allowed:
        entry = audit_logger.log(
            actor=actor, tool="refund_payment", params={"payment_id": payment_id, "amount_paise": amount_paise},
            decision="blocked", reason=decision.reason,
        )
        return ToolResult(blocked=True, entry=entry)

    try:
        refund = call_with_retry(
            lambda: razorpay_client.refund_payment(payment_id=payment_id, amount_paise=amount_paise, notes={"actor": actor}),
            tool="refund_payment", actor=actor, params={"payment_id": payment_id, "amount_paise": amount_paise},
        )
    except RazorpayCallFailed as exc:
        state_manager.suspend(payment_id, f"refund failed after retries: {exc}")
        entry = audit_logger.log(
            actor=actor, tool="refund_payment", params={"payment_id": payment_id, "amount_paise": amount_paise},
            decision="blocked", reason=f"Razorpay unavailable after retries: {exc}",
        )
        return ToolResult(blocked=True, entry=entry)

    entry = audit_logger.log(
        actor=actor, tool="refund_payment", params={"payment_id": payment_id, "amount_paise": amount_paise},
        decision="allowed", reason=decision.reason,
        result={"refund_id": refund["id"], "status": refund["status"]},
    )
    return ToolResult(blocked=False, data={"refund": refund}, entry=entry)


def get_audit_trail() -> list[dict[str, Any]]:
    return [e.model_dump() for e in audit_logger.all_entries()]


def get_state_snapshot() -> list[dict[str, Any]]:
    return [t.model_dump() for t in state_manager.snapshot()]

def get_campaign_stats(actor: str = ACTOR_DEFAULT) -> ToolResult:
    
    stats = {
        "baseline_conversion_rate": "2.4%",
        "agent_assisted_conversion_rate": "8.7%",
        "checkout_only_AOV": "₹499",
        "checkout_with_upsell_AOV": "₹648",
        "upsell_attach_rate": "34%"
    }
    entry = audit_logger.log(
        actor=actor, tool="get_campaign_stats", params={}, decision="allowed",
        reason="Read-only stats", result=stats
    )
    return ToolResult(blocked=False, data={"campaign_stats": stats}, entry=entry)
