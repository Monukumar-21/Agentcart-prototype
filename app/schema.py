"""
Pydantic models for requests, responses, configs, and everything in between.
"""

from __future__ import annotations
from typing import Optional, Literal, Any
from pydantic import BaseModel, Field, field_validator


class CatalogItem(BaseModel):
    sku: str
    name: str
    price_rupees: float
    stock: int
    image_url: Optional[str] = None
    ratings: Optional[float] = None
    no_of_ratings: Optional[float] = None
    actual_price_rupees: Optional[float] = None
    category: Optional[str] = None
    link: Optional[str] = None


class UpsellSuggestion(BaseModel):
    product: CatalogItem
    reason: str
    discount_percent: float = 0.0
    discounted_price_rupees: Optional[float] = None


class CheckoutRequest(BaseModel):
    actor: str = Field(..., min_length=1, description="Who's making the request")
    sku: str
    qty: int = 1

    @field_validator("qty")
    @classmethod
    def qty_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("qty must be positive")
        return v


class AddToCartRequest(BaseModel):
    actor: str
    sku: str
    qty: int = 1

    @field_validator("qty")
    @classmethod
    def qty_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("qty must be positive")
        return v


class RemoveFromCartRequest(BaseModel):
    actor: str
    sku: str
    qty: int = 1

    @field_validator("qty")
    @classmethod
    def qty_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("qty must be positive")
        return v


class CheckoutCartRequest(BaseModel):
    actor: str


class VerifyPaymentRequest(BaseModel):
    actor: str
    order_id: str
    payment_id: str
    signature: str


class UpsellRequest(BaseModel):
    actor: str
    sku: Optional[str] = None


class SearchRequest(BaseModel):
    query: str
    top_n: int = 7
    page: int = 0


class RecommendationRequest(BaseModel):
    sku: str
    top_n: int = 7


class RefundRequest(BaseModel):
    actor: str
    order_id: str
    sku: str
    qty: int = 1

    @field_validator("qty")
    @classmethod
    def qty_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("qty must be positive")
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
    actor: Optional[str] = None
    items: dict[str, int] = Field(default_factory=dict)
    status: Literal[
        "created", "pending_payment", "paid", "refund_pending", "refunded", "suspended", "failed"
    ]
    amount_rupees: Optional[float] = None
    history: list[str] = []


class ToolResult(BaseModel):
    """What every orchestrator call returns — blocked flag, optional data, and audit entry."""
    blocked: bool
    data: Optional[dict[str, Any]] = None
    entry: AuditEntry


class Settings(BaseModel):
    max_auto_approve_rupees: float
    max_actions_per_minute: int
    max_qty_per_order: int
    blocked_actors: list[str] = Field(default_factory=list)
