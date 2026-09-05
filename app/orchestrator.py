"""
Orchestrator — the central nervous system of AgentCart.

This sits between the UI/MCP interfaces and the domain logic (catalog, cart, payment).
Every action must pass through here so that guardrails, policy checks, and audit 
logging are applied consistently regardless of how the system is accessed.
"""

from __future__ import annotations
import uuid
import os
from datetime import datetime, timezone
from pydantic import ValidationError

from app import guardrails, policy_engine, state_manager, cart, razorpay_client
from app import recommendation_engine as catalog
from app import upsell_engine
from app.audits import audit_logger
from app.retry import call_with_retry, RazorpayCallFailed
from app.schema import (
    ToolResult,
    CheckoutRequest,
    AddToCartRequest,
    RemoveFromCartRequest,
    CheckoutCartRequest,
    VerifyPaymentRequest,
    RefundRequest,
    SearchRequest,
    RecommendationRequest,
    UpsellRequest,
    Settings,
)


def _block(actor: str, tool: str, params: dict, reason: str, rule: str | None = None) -> ToolResult:
    """Helper to log and return a blocked action."""
    entry = audit_logger.log(
        actor=actor,
        tool=tool,
        params=params,
        decision="blocked",
        reason=reason,
        result={"rule": rule} if rule else None,
    )
    return ToolResult(blocked=True, entry=entry)


def _allow(actor: str, tool: str, params: dict, reason: str, data: dict | None = None, audit_data: dict | None = None) -> ToolResult:
    """Helper to log and return an allowed action. 
    audit_data is used for the log if provided, otherwise it falls back to data."""
    entry = audit_logger.log(
        actor=actor,
        tool=tool,
        params=params,
        decision="allowed",
        reason=reason,
        result=audit_data if audit_data is not None else data,
    )
    return ToolResult(blocked=False, data=data, entry=entry)


# ── Read/Search Actions ───────────────────────────────────────────────────────

def search_products(actor: str, query: str, top_n: int = 7, page: int = 0) -> ToolResult:
    req = SearchRequest(query=query, top_n=top_n, page=page)
    results = catalog.search_products(req.query, top_n=req.top_n, page=req.page)
    data = {"products": [r.model_dump() for r in results]}
    return _allow(actor, "search_products", req.model_dump(), "Read-only search", data, audit_data={"count": len(results)})


def get_recommendations(actor: str, sku: str, top_n: int = 7) -> ToolResult:
    req = RecommendationRequest(sku=sku, top_n=top_n)
    results = catalog.get_recommendations(req.sku, top_n=req.top_n)
    data = {"recommendations": [r.model_dump() for r in results]}
    return _allow(actor, "get_recommendations", req.model_dump(), f"Got recommendations for {sku}", data, audit_data={"count": len(results)})


def get_trending(actor: str, top_n: int = 7) -> ToolResult:
    results = catalog.get_trending(top_n=top_n)
    data = {"trending": [r.model_dump() for r in results]}
    return _allow(actor, "get_trending", {"top_n": top_n}, "Read-only trending", data, audit_data={"count": len(results)})


# ── Cart Actions ─────────────────────────────────────────────────────────────

def get_current_cart(actor: str) -> ToolResult:
    current_cart = cart.get_cart(actor)
    pricing = upsell_engine.get_cart_pricing(current_cart)
    return _allow(actor, "get_cart", {}, "Viewed cart", {"cart": current_cart, "pricing": pricing})


def add_to_cart(actor: str, sku: str, qty: int = 1) -> ToolResult:
    try:
        req = AddToCartRequest(actor=actor, sku=sku, qty=qty)
    except ValidationError as e:
        return _block(actor, "add_to_cart", {"sku": sku, "qty": qty}, str(e), "schema")

    gr = guardrails.check_add_to_cart(req.actor, req.sku, req.qty)
    if not gr.passed:
        return _block(req.actor, "add_to_cart", req.model_dump(), gr.reason, gr.rule)

    updated_cart = cart.add_item(req.actor, req.sku, req.qty)
    return _allow(req.actor, "add_to_cart", req.model_dump(), "Item added to cart", {"cart": updated_cart})


def remove_from_cart(actor: str, sku: str, qty: int = 1) -> ToolResult:
    try:
        req = RemoveFromCartRequest(actor=actor, sku=sku, qty=qty)
    except ValidationError as e:
        return _block(actor, "remove_from_cart", {"sku": sku, "qty": qty}, str(e), "schema")

    updated_cart = cart.remove_item(req.actor, req.sku, req.qty)
    return _allow(req.actor, "remove_from_cart", req.model_dump(), "Item removed from cart", {"cart": updated_cart})


# ── Upsell Actions ────────────────────────────────────────────────────────────

def suggest_upsell(actor: str, context_sku: str | None = None) -> ToolResult:
    """
    Get upsell suggestions for the current cart, optionally using a specific SKU 
    as additional context (e.g., if cart is empty but user is viewing an item).
    """
    try:
        req = UpsellRequest(actor=actor, sku=context_sku)
    except ValidationError as e:
        return _block(actor, "suggest_upsell", {"sku": context_sku}, str(e), "schema")

    current_cart = cart.get_cart(req.actor)
    cart_items = current_cart.copy()

    # if cart is empty but we have a context SKU, fake it for suggestions
    if not cart_items and req.sku:
        cart_items = {req.sku: 1}

    cart_total_rupees = 0.0
    for sku, qty in cart_items.items():
        item = catalog.find_by_sku(sku)
        if item:
            cart_total_rupees += item.price_rupees * qty

    suggestions = upsell_engine.get_upsell_suggestions(cart_items, cart_total_rupees)
    
    data = {
        "suggestions": [s.model_dump() for s in suggestions],
        "cart_total_rupees": cart_total_rupees,
    }
    return _allow(req.actor, "suggest_upsell", {"sku": req.sku, "cart": current_cart}, "Smart cross-sell recommendation", data, audit_data={"suggested_count": len(suggestions)})


# ── Checkout & Payment Actions ────────────────────────────────────────────────

def checkout_cart(actor: str) -> ToolResult:
    try:
        req = CheckoutCartRequest(actor=actor)
    except ValidationError as e:
        return _block(actor, "checkout_cart", {}, str(e), "schema")

    current_cart = cart.get_cart(req.actor)
    
    gr = guardrails.check_cart_checkout(req.actor, current_cart)
    if not gr.passed:
        return _block(req.actor, "checkout_cart", {"cart": current_cart}, gr.reason, gr.rule)

    pricing = upsell_engine.get_cart_pricing(current_cart)
    total_rupees = pricing["total_rupees"]
    total_paise = int(total_rupees * 100)
    
    pr = policy_engine.evaluate(actor=req.actor, tool="checkout_cart", amount_rupees=total_rupees)
    if not pr.allowed:
        return _block(req.actor, "checkout_cart", {"cart": current_cart, "amount_rupees": total_rupees}, pr.reason, pr.rule)

    receipt = f"rcpt_{uuid.uuid4().hex[:8]}"

    def _do_checkout():
        return razorpay_client.create_order(
            total_paise,
            receipt=receipt,
            notes={"actor": req.actor, "source": "agentcart-prototype"},
        )

    try:
        order = call_with_retry(_do_checkout, tool="checkout_cart", actor=req.actor, params={"cart": current_cart, "amount_rupees": total_rupees})
    except RazorpayCallFailed as e:
        return _block(req.actor, "checkout_cart", {"cart": current_cart, "amount_rupees": total_rupees}, f"Razorpay API failed after retries: {e}", "api_failure")

    state_manager.create(order["id"], items=current_cart, actor=req.actor, amount_rupees=total_rupees)
    
    payment_link = f"{os.getenv('BASE_URL', 'http://localhost:8000')}/pay/{order['id']}"

    return _allow(
        req.actor,
        "checkout_cart",
        {"cart": current_cart, "amount_rupees": total_rupees},
        pr.reason,
        {"order": order, "payment_link": payment_link},
        audit_data={"order_id": order["id"], "status": "created"}
    )


def verify_payment(actor: str, order_id: str, payment_id: str, signature: str) -> ToolResult:
    try:
        req = VerifyPaymentRequest(actor=actor, order_id=order_id, payment_id=payment_id, signature=signature)
    except ValidationError as e:
        return _block(actor, "verify_payment", {"order_id": order_id}, str(e), "schema")

    tx = state_manager.get(req.order_id)
    if not tx:
        return _block(req.actor, "verify_payment", {"order_id": req.order_id, "payment_id": req.payment_id}, f"Order {req.order_id} not found", "not_found")

    if not razorpay_client.verify_signature(req.order_id, req.payment_id, req.signature):
        state_manager.transition(req.order_id, "failed")
        return _block(req.actor, "verify_payment", {"order_id": req.order_id, "payment_id": req.payment_id}, "Invalid signature", "signature_invalid")

    state_manager.transition(req.order_id, "paid")
    
    if tx.actor:
        cart.clear_cart(tx.actor)
        
    for sku, qty in tx.items.items():
        catalog.decrement_stock(sku, qty)

    return _allow(req.actor, "verify_payment", {"order_id": req.order_id, "payment_id": req.payment_id}, "Signature valid", audit_data=None)


def refund_payment(actor: str, order_id: str, sku: str, qty: int) -> ToolResult:
    try:
        req = RefundRequest(actor=actor, order_id=order_id, sku=sku, qty=qty)
    except ValidationError as e:
        return _block(actor, "refund_payment", {"order_id": order_id, "sku": sku, "qty": qty}, str(e), "schema")

    tx = state_manager.get(req.order_id)
    if not tx:
        return _block(req.actor, "refund_payment", req.model_dump(), f"Order {req.order_id} not found", "not_found")
        
    if tx.status != "paid":
        return _block(req.actor, "refund_payment", req.model_dump(), f"Cannot refund order in status '{tx.status}'", "invalid_state")
        
    if req.sku not in tx.items or tx.items[req.sku] < req.qty:
        return _block(req.actor, "refund_payment", req.model_dump(), f"SKU {req.sku} not in order or qty {req.qty} exceeds ordered", "invalid_item")

    pricing = upsell_engine.get_cart_pricing(tx.items)
    item_pricing = next((item for item in pricing["items"] if item["sku"] == req.sku), None)
    
    if not item_pricing:
        return _block(req.actor, "refund_payment", req.model_dump(), f"Could not calculate pricing for {req.sku}", "pricing_error")
        
    final_price_rupees = item_pricing["final_price_rupees"]
    amount_rupees = round(final_price_rupees * req.qty, 2)
    
    try:
        payments = razorpay_client.fetch_order_payments(req.order_id)
        captured = next((p for p in payments if p.get("status") == "captured"), None)
        if not captured:
            return _block(req.actor, "refund_payment", req.model_dump(), "No captured payment found for order", "no_payment")
        payment_id = captured["id"]
    except Exception as e:
        return _block(req.actor, "refund_payment", req.model_dump(), f"Failed to fetch payments: {e}", "api_failure")

    gr = guardrails.check_refund(req.actor, payment_id, amount_rupees)
    if not gr.passed:
        return _block(req.actor, "refund_payment", req.model_dump(), gr.reason, gr.rule)

    pr = policy_engine.evaluate(actor=req.actor, tool="refund_payment", amount_rupees=amount_rupees)
    if not pr.allowed:
        return _block(req.actor, "refund_payment", req.model_dump(), pr.reason, pr.rule)

    amount_paise = int(amount_rupees * 100)

    def _do_refund():
        return razorpay_client.create_refund(payment_id, amount_paise)

    try:
        refund_resp = call_with_retry(_do_refund, tool="refund_payment", actor=req.actor, params=req.model_dump())
    except RazorpayCallFailed as e:
        return _block(req.actor, "refund_payment", req.model_dump(), f"Razorpay API failed after retries: {e}", "api_failure")

    tx.items[req.sku] -= req.qty

    return _allow(
        req.actor, 
        "refund_payment", 
        req.model_dump(), 
        pr.reason, 
        {"refund": refund_resp},
        audit_data={"refund_id": refund_resp["id"], "status": refund_resp["status"]}
    )


# ── Admin & Settings Actions ──────────────────────────────────────────────────

def get_audit_trail() -> list[dict]:
    return [e.model_dump() for e in audit_logger.all_entries()]


def get_campaign_stats(actor: str) -> ToolResult:
    # simulated baseline stats
    data = {
        "baseline_attach_rate": "12%",
        "agent_assisted_attach_rate": "34%",
        "active_campaigns": ["summer_sale", "bundle_deals"],
    }
    return _allow(actor, "get_campaign_stats", {}, "Viewed stats", data)


def get_settings(actor: str) -> Settings:
    gr = guardrails.get_settings()
    pe = policy_engine.get_settings()
    settings = Settings(
        max_auto_approve_rupees=pe["max_auto_approve_rupees"],
        max_actions_per_minute=pe["max_actions_per_minute"],
        max_qty_per_order=gr["max_qty_per_order"],
        blocked_actors=gr["blocked_actors"]
    )
    _allow(actor, "get_settings", {}, "Read-only settings", settings.model_dump())
    return settings


def update_settings(actor: str, max_auto_approve_rupees: float, max_actions_per_minute: int, max_qty_per_order: int, blocked_actors: list[str]) -> Settings:
    policy_engine.update_settings(max_auto_approve_rupees, max_actions_per_minute)
    guardrails.update_settings(max_qty_per_order, blocked_actors)
    
    settings = Settings(
        max_auto_approve_rupees=max_auto_approve_rupees,
        max_actions_per_minute=max_actions_per_minute,
        max_qty_per_order=max_qty_per_order,
        blocked_actors=blocked_actors
    )
    _allow(actor, "update_settings", settings.model_dump(), "Settings updated", settings.model_dump())
    return settings


# ── Reconciliation Agent ──────────────────────────────────────────────────────

def reconcile_stuck_orders(actor: str = "reconciliation-agent") -> ToolResult:
    """
    Agentic reconciliation: scan for orders stuck in 'created' status,
    query Razorpay to check if they were actually paid, and heal the
    system state if so.

    This handles the graceful failure case where a user pays but a network
    timeout prevents our /checkout/verify callback from being reached.
    """
    all_txns = state_manager.snapshot()
    stuck_orders = [tx for tx in all_txns if tx.status == "created"]

    if not stuck_orders:
        return _allow(
            actor,
            "reconcile_orders",
            {},
            "No stuck orders found — all transactions are healthy",
            {"reconciled": [], "still_pending": [], "checked": 0},
        )

    reconciled = []
    still_pending = []

    for tx in stuck_orders:
        try:
            payments = razorpay_client.fetch_order_payments(tx.order_id)
        except Exception as e:
            # If Razorpay API fails, log it and skip this order
            audit_logger.log(
                actor=actor,
                tool="reconcile_orders",
                params={"order_id": tx.order_id},
                decision="blocked",
                reason=f"Failed to fetch payments from Razorpay: {e}",
                result={"rule": "api_failure"},
            )
            still_pending.append(tx.order_id)
            continue

        # Check if any payment has status 'captured' (i.e. successfully paid)
        captured_payment = next(
            (p for p in payments if p.get("status") == "captured"),
            None,
        )

        if captured_payment:
            # ── Heal the order ────────────────────────────────────────
            state_manager.transition(tx.order_id, "paid")

            if tx.actor:
                cart.clear_cart(tx.actor)

            for sku, qty in tx.items.items():
                catalog.decrement_stock(sku, qty)

            reconciled.append({
                "order_id": tx.order_id,
                "payment_id": captured_payment["id"],
                "actor": tx.actor,
                "amount_rupees": tx.amount_rupees,
            })

            # Log each recovered order individually for the audit trail
            audit_logger.log(
                actor=actor,
                tool="reconcile_orders",
                params={"order_id": tx.order_id},
                decision="allowed",
                reason=f"Recovered stuck order — Razorpay confirms payment {captured_payment['id']}",
                result={
                    "order_id": tx.order_id,
                    "payment_id": captured_payment["id"],
                    "status": "paid",
                },
            )
        else:
            still_pending.append(tx.order_id)

    summary = {
        "checked": len(stuck_orders),
        "reconciled": reconciled,
        "still_pending": still_pending,
    }

    reason = (
        f"Reconciliation complete: {len(reconciled)} orders recovered, "
        f"{len(still_pending)} still pending"
    )

    return _allow(actor, "reconcile_orders", {}, reason, summary)
