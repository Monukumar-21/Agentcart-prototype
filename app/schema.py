"""
schema.py -- the single source of truth for what every request, decision,
and log entry looks like. Guardrails, the policy engine, the orchestrator,
and the API layer all import these models instead of passing raw dicts
around, so a malformed request is rejected before it reaches any business
logic at all.
"""

from __future__ import annotations
from typing import Optional, Literal, Any
from pydantic import BaseModel, Field, field_validator


class CatalogItem(BaseModel):
    sku: str
    name: str
    price_paise: int
    stock: int
    upsell_sku: Optional[str] = None


class CheckoutRequest(BaseModel):
    actor: str = Field(..., min_length=1, description="Calling agent's identity")
    sku: str
    qty: int = 1

    @field_validator("qty")
    @classmethod
    def qty_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("qty must be positive")
        return v


class VerifyPaymentRequest(BaseModel):
    actor: str
    order_id: str
    payment_id: str
    signature: str


class UpsellRequest(BaseModel):
    actor: str
    sku: str


class RefundRequest(BaseModel):
    actor: str
    payment_id: str
    amount_paise: int

    @field_validator("amount_paise")
    @classmethod
    def amount_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("amount_paise must be positive")
        return v


class GuardrailResult(BaseModel):
    passed: bool
    reason: str
    rule: Optional[str] = None


class PolicyDecision(BaseModel):
    allowed: bool
    reason: str
    rule: Optional[str] = None


class AuditEntry(BaseModel):
    ts: str
    actor: str
    tool: str
    params: dict[str, Any] = {}
    decision: Literal["allowed", "blocked"]
    reason: str
    result: Optional[dict[str, Any]] = None


class TransactionState(BaseModel):
    order_id: str
    sku: Optional[str] = None
    actor: Optional[str] = None
    status: Literal[
        "created", "pending_payment", "paid", "refund_pending", "refunded", "suspended", "failed"
    ]
    amount_paise: Optional[int] = None
    history: list[str] = []


class ToolResult(BaseModel):
    """Uniform envelope every orchestrator tool call returns."""

    blocked: bool
    data: Optional[dict[str, Any]] = None
    entry: AuditEntry
