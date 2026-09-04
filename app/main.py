"""
main.py -- REST API + dashboard front door. All business logic lives in
orchestrator.py; this file only translates HTTP <-> orchestrator calls and
renders the dashboard template.
"""

from __future__ import annotations
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()  # noqa: E402  -- must run before other app modules read env vars

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from app import orchestrator, razorpay_client
from app.schema import CheckoutRequest, VerifyPaymentRequest, UpsellRequest, RefundRequest

app = FastAPI(title="AgentCart prototype")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.get("/catalog")
def get_catalog(actor: str = "demo-buyer-agent"):
    result = orchestrator.get_catalog(actor)
    return result.data


@app.post("/checkout/order")
def create_checkout_order(req: CheckoutRequest):
    result = orchestrator.create_checkout_order(req.actor, req.sku, req.qty)
    status = 403 if result.blocked else 200
    return JSONResponse(status_code=status, content=result.model_dump())


@app.post("/checkout/verify")
def verify_payment(req: VerifyPaymentRequest):
    result = orchestrator.verify_payment(req.actor, req.order_id, req.payment_id, req.signature)
    status = 403 if result.blocked else 200
    return JSONResponse(status_code=status, content=result.model_dump())


@app.post("/upsell/suggest")
def suggest_upsell(req: UpsellRequest):
    result = orchestrator.suggest_upsell(req.actor, req.sku)
    return result.model_dump()


@app.post("/refund")
def refund_payment(req: RefundRequest):
    result = orchestrator.refund_payment(req.actor, req.payment_id, req.amount_paise)
    status = 403 if result.blocked else 200
    return JSONResponse(status_code=status, content=result.model_dump())


@app.get("/audit")
def get_audit_trail():
    return orchestrator.get_audit_trail()


@app.get("/state")
def get_state():
    return orchestrator.get_state_snapshot()


@app.get("/pay/{order_id}", include_in_schema=False)
def pay_order(request: Request, order_id: str):
    tx = orchestrator.state_manager.get(order_id)
    if not tx:
        return JSONResponse(status_code=404, content={"error": "Order not found"})
    
    return templates.TemplateResponse(
        "pay.html",
        {
            "request": request,
            "mock_mode": razorpay_client.MOCK_MODE,
            "razorpay_key_id": os.getenv("RAZORPAY_KEY_ID", ""),
            "order_id": order_id,
            "amount_paise": tx.amount_paise,
            "actor": tx.actor,
        },
    )


@app.get("/", include_in_schema=False)
def dashboard(request: Request):
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "mock_mode": razorpay_client.MOCK_MODE,
            "catalog": [i.model_dump() for i in orchestrator.catalog.get_catalog()],
            "razorpay_key_id": os.getenv("RAZORPAY_KEY_ID", ""),
        },
    )


if __name__ == "__main__":
    import os
    import uvicorn

    uvicorn.run("app.main:app", host="localhost", port=int(os.getenv("PORT", "8000")), reload=False)
