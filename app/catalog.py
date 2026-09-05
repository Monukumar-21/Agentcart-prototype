"""
Catalog module — thin wrapper over the recommendation engine.
"""

from __future__ import annotations
from typing import Optional
from app.schema import CatalogItem
from app import recommendation_engine


def get_catalog(top_n: int = 7) -> list[CatalogItem]:
    return recommendation_engine.get_trending(top_n=top_n)


def find_by_sku(sku: str) -> Optional[CatalogItem]:
    return recommendation_engine.find_by_sku(sku)


def decrement_stock(sku: str, qty: int) -> Optional[CatalogItem]:
    return recommendation_engine.decrement_stock(sku, qty)


def search(query: str, top_n: int = 7, page: int = 0) -> list[CatalogItem]:
    return recommendation_engine.search_products(query=query, top_n=top_n, page=page)


def get_recommendations(sku: str, top_n: int = 7) -> list[CatalogItem]:
    return recommendation_engine.get_recommendations(sku=sku, top_n=top_n)


def get_trending(top_n: int = 7) -> list[CatalogItem]:
    return recommendation_engine.get_trending(top_n=top_n)
