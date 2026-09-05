"""
FastAPI REST wrapper around the orchestrator + a web dashboard.
"""

from __future__ import annotations
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import orchestrator, state_manager
from app.audits import audit_logger
from app.schema import (
    AddToCartRequest,
    RemoveFromCartRequest,
    CheckoutCartRequest,
    RefundRequest,
    Settings,
    UpsellRequest,
)

# load environment variables
from dotenv import load_dotenv
load_dotenv()

from app import razorpay_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    # setup logic could go here
    yield
    # teardown logic could go here


app = FastAPI(title="AgentCart", lifespan=lifespan)

# setup templates
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


# ── Web Dashboard (Jinja2) ────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Render the main dashboard."""
    catalog_data = orchestrator.get_trending("web", top_n=12).data["trending"]
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "catalog": catalog_data,
            "mock_mode": razorpay_client.MOCK_MODE,
            "razorpay_key_id": os.getenv("RAZORPAY_KEY_ID", ""),
        },
    )


@app.get("/pay/{order_id}", response_class=HTMLResponse)
async def pay_page(request: Request, order_id: str):
    """
    Render a simulated payment page.
    In real life, this would load Razorpay Checkout.js.
    """
    tx = state_manager.get(order_id)
    if not tx:
        return HTMLResponse(content="Order not found", status_code=404)

    return templates.TemplateResponse(
        "pay.html",
        {
            "request": request,
            "order_id": order_id,
            "amount_rupees": tx.amount_rupees,
            "mock_mode": razorpay_client.MOCK_MODE,
            "razorpay_key_id": os.getenv("RAZORPAY_KEY_ID", ""),
            "actor": tx.actor or "web-buyer",
        },
    )


@app.post("/pay/mock-submit")
async def mock_submit(order_id: str = Form(...)):
    """Handle form submission from the mock payment page."""
    orchestrator.verify_payment(
        "web-buyer",
        order_id,
        f"pay_mock_{order_id}",
        "mock_sig"
    )
    return HTMLResponse(
        f"<h3>Payment Successful for {order_id}!</h3><p><a href='/'>Back to dashboard</a></p>"
    )


# ── REST API (delegates to orchestrator) ──────────────────────────────────────

@app.get("/catalog/search")
def api_search_products(q: str, top_n: int = 7, page: int = 0):
    res = orchestrator.search_products("api", q, top_n, page)
    return res.data or {}


@app.get("/catalog/trending")
def api_get_trending(top_n: int = 7):
    res = orchestrator.get_trending("api", top_n)
    return res.data or {}


@app.get("/catalog/recommendations/{sku}")
def api_get_recommendations(sku: str, top_n: int = 7):
    res = orchestrator.get_recommendations("api", sku, top_n)
    return res.data or {}


@app.get("/product/{sku}")
def api_get_product(sku: str):
    from fastapi import HTTPException
    from app import recommendation_engine as catalog
    item = catalog.find_by_sku(sku)
    if not item:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"product": item.model_dump()}


@app.post("/cart")
def api_add_to_cart(req: AddToCartRequest):
    return orchestrator.add_to_cart(req.actor, req.sku, req.qty).model_dump()


@app.post("/cart/remove")
def api_remove_from_cart(req: RemoveFromCartRequest):
    return orchestrator.remove_from_cart(req.actor, req.sku, req.qty).model_dump()


@app.get("/cart")
def api_get_cart(actor: str):
    res = orchestrator.get_current_cart(actor)
    return res.data or {}


@app.post("/upsell/suggest")
def api_suggest_upsell(req: UpsellRequest):
    return orchestrator.suggest_upsell(req.actor, req.sku).model_dump()


@app.post("/checkout/cart")
def api_checkout_cart(req: CheckoutCartRequest):
    return orchestrator.checkout_cart(req.actor).model_dump()


@app.post("/refund")
def api_refund(req: RefundRequest):
    return orchestrator.refund_payment(req.actor, req.order_id, req.sku, req.qty).model_dump()


@app.get("/audit")
def api_audit():
    return [e.model_dump() for e in audit_logger.all_entries()]


@app.get("/state")
def api_state():
    return [s.model_dump() for s in state_manager.snapshot()]


@app.post("/reconcile")
def api_reconcile():
    """Trigger the agentic reconciliation agent to heal stuck orders."""
    return orchestrator.reconcile_stuck_orders().model_dump()


@app.get("/settings")
def api_get_settings():
    return orchestrator.get_settings("api").model_dump()


@app.post("/settings")
def api_update_settings(req: Settings):
    return orchestrator.update_settings(
        "api",
        req.max_auto_approve_rupees,
        req.max_actions_per_minute,
        req.max_qty_per_order,
        req.blocked_actors
    ).model_dump()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    print(f"Starting server on port {port}")
    uvicorn.run("app.main:app", host="localhost", port=port, reload=True)
