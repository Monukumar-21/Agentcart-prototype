"""
catalog.py -- stand-in for "the merchant's database, exposed via an API
layer". Prices are in paise (Razorpay's smallest INR unit).
"""

from __future__ import annotations
from typing import Optional
from app.schema import CatalogItem

_CATALOG: list[CatalogItem] = [
    CatalogItem(sku="PHONE-CASE-01", name="Silicone phone case", price_paise=49900,
                stock=42, upsell_sku="SCREEN-GUARD-01"),
    CatalogItem(sku="SCREEN-GUARD-01", name="Tempered glass screen guard", price_paise=29900,
                stock=120, upsell_sku=None),
    CatalogItem(sku="WIRELESS-CHARGER-01", name="15W wireless charger", price_paise=129900,
                stock=15, upsell_sku=None),
]


def get_catalog() -> list[CatalogItem]:
    return _CATALOG


def find_by_sku(sku: str) -> Optional[CatalogItem]:
    return next((p for p in _CATALOG if p.sku == sku), None)


def decrement_stock(sku: str, qty: int) -> Optional[CatalogItem]:
    item = find_by_sku(sku)
    if item:
        item.stock = max(0, item.stock - qty)
    return item
