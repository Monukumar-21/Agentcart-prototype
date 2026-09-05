"""
Recommendation engine — loads products from CSV, builds a TF-IDF similarity
matrix, and handles search, recommendations, and trending queries.

Uses ~8,700 products from the cleaned Amazon dataset. SKUs are assigned
sequentially (AMZN-0000, AMZN-0001, ...) and categories are inferred
from product names.
"""

from __future__ import annotations

import os
import re
import random
import threading
from pathlib import Path
from typing import Optional

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from app.schema import CatalogItem

_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "cleaned_amazon_products.csv",
)

# keyword lists for inferring product categories from names
_CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("phone",       ["phone", "mobile", "smartphone", "iphone", "galaxy", "redmi",
                     "oneplus", "realme", "iqoo", "poco", "vivo", "oppo", "motorola",
                     "nokia", "samsung galaxy m", "samsung galaxy s", "samsung galaxy a"]),
    ("earbuds",     ["earbud", "earphone", "airpod", "airdope", "tws", "truly wireless",
                     "in-ear", "in ear"]),
    ("headphones",  ["headphone", "headset", "over-ear", "over ear", "noise cancelling headphone"]),
    ("neckband",    ["neckband", "neck band"]),
    ("charger",     ["charger", "adapter", "power adapter", "wall adapter", "fast charge"]),
    ("cable",       ["cable", "usb-c", "usb c", "lightning", "micro usb", "type-c", "type c"]),
    ("power_bank",  ["power bank", "powerbank", "portable charger"]),
    ("smartwatch",  ["smart watch", "smartwatch", "watch", "fitness band", "fitness tracker"]),
    ("laptop",      ["laptop", "notebook", "macbook", "chromebook"]),
    ("tablet",      ["tablet", "ipad"]),
    ("mouse",       ["mouse", "wireless mouse", "bluetooth mouse", "gaming mouse"]),
    ("keyboard",    ["keyboard", "mechanical keyboard"]),
    ("speaker",     ["speaker", "bluetooth speaker", "soundbar", "sound bar"]),
    ("camera",      ["camera", "dslr", "mirrorless", "webcam", "action camera", "gopro"]),
    ("tv",          ["television", "smart tv", "led tv", "oled tv", "android tv"]),
    ("case",        ["case", "cover", "back cover", "phone case", "protective case"]),
    ("screen_guard",["screen guard", "screen protector", "tempered glass"]),
    ("memory_card", ["memory card", "sd card", "micro sd", "pendrive", "pen drive", "flash drive"]),
    ("tripod",      ["tripod", "selfie stick", "gimbal"]),
    ("stand",       ["stand", "laptop stand", "phone stand", "holder", "mount"]),
    ("bag",         ["bag", "backpack", "sleeve", "pouch", "laptop bag"]),
    ("hub",         ["hub", "usb hub", "docking station", "dongle"]),
    ("cleaning",    ["cleaning", "cleaner", "cleaning kit"]),
    ("strap",       ["strap", "band", "watch band", "watch strap"]),
    ("router",      ["router", "wifi", "wi-fi", "modem", "extender"]),
    ("storage",     ["hard drive", "ssd", "hard disk", "external drive", "hdd"]),
    ("gaming",      ["gaming", "controller", "gamepad", "joystick"]),
    ("printer",     ["printer", "ink", "toner", "scanner"]),
]


def _infer_category(name: str) -> str:
    name_lower = name.lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        for kw in keywords:
            if kw in name_lower:
                return category
    return "electronics"  # fallback


def _clean_text(text: str) -> str:
    """Strip punctuation and lowercase for TF-IDF."""
    if not isinstance(text, str):
        return ""
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s]', '', text)
    return text


# loaded once, shared across requests
_lock = threading.Lock()
_df: Optional[pd.DataFrame] = None
_cosine_sim = None
_sku_map: dict[str, int] = {}          # SKU -> DataFrame row index
_stock_overrides: dict[str, int] = {}   # SKU -> simulated stock level
_loaded = False


def _ensure_loaded():
    """Load the CSV and build the similarity matrix on first access."""
    global _df, _cosine_sim, _sku_map, _stock_overrides, _loaded
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        print("[recommendation_engine] Loading product data...")
        df = pd.read_csv(_CSV_PATH)
        df = df.reset_index(drop=True)

        df["sku"] = [f"AMZN-{i:04d}" for i in range(len(df))]

        # make sure price columns are numeric
        df["discount_price"] = pd.to_numeric(df["discount_price"], errors="coerce").fillna(0)
        df["actual_price"] = pd.to_numeric(df["actual_price"], errors="coerce").fillna(0)
        df["ratings"] = pd.to_numeric(df["ratings"], errors="coerce").fillna(0)
        df["no_of_ratings"] = pd.to_numeric(df["no_of_ratings"], errors="coerce").fillna(0)

        df["category"] = df["name"].apply(_infer_category)
        df["tags"] = df["name"].apply(_clean_text)

        print("[recommendation_engine] Building similarity matrix...")
        tfidf = TfidfVectorizer(stop_words="english")
        tfidf_matrix = tfidf.fit_transform(df["tags"])
        import numpy as np
        _cosine_sim = linear_kernel(tfidf_matrix, tfidf_matrix).astype(np.float32)

        _sku_map = {row["sku"]: idx for idx, row in df.iterrows()}

        # simulate stock levels (deterministic seed so it's reproducible)
        random.seed(42)
        _stock_overrides = {row["sku"]: random.randint(10, 200) for _, row in df.iterrows()}

        _df = df
        _loaded = True
        print(f"[recommendation_engine] Ready — {len(df)} products, {df['category'].nunique()} categories")


def _row_to_catalog_item(row, stock: Optional[int] = None) -> CatalogItem:
    sku = row["sku"]
    if stock is None:
        stock = _stock_overrides.get(sku, 0)
    price_rupees = float(row["discount_price"]) if row["discount_price"] > 0 else float(row["actual_price"])
    actual_price_rupees = float(row["actual_price"]) if row["actual_price"] > 0 else price_rupees
    return CatalogItem(
        sku=sku,
        name=str(row["name"]),
        price_rupees=price_rupees,
        stock=stock,
        image_url=str(row.get("image", "")) if pd.notna(row.get("image")) else None,
        ratings=float(row["ratings"]) if row["ratings"] > 0 else None,
        no_of_ratings=float(row["no_of_ratings"]) if row["no_of_ratings"] > 0 else None,
        actual_price_rupees=actual_price_rupees,
        category=str(row["category"]),
        link=str(row.get("link", "")) if pd.notna(row.get("link")) else None,
    )


# -- public functions --

def search_products(query: str, top_n: int = 7, page: int = 0) -> list[CatalogItem]:
    """Fuzzy search using TF-IDF. Returns paginated, in-stock results."""
    _ensure_loaded()
    query_clean = _clean_text(query)
    if not query_clean.strip():
        return []

    tfidf = TfidfVectorizer(stop_words="english")
    all_tags = _df["tags"].tolist() + [query_clean]
    tfidf_matrix = tfidf.fit_transform(all_tags)

    # compare query vector against every product
    query_vec = tfidf_matrix[-1]
    product_vecs = tfidf_matrix[:-1]
    sim_scores = linear_kernel(query_vec, product_vecs).flatten()

    # grab extra results to account for out-of-stock filtering
    buffer_size = (page + 1) * top_n * 3
    top_indices = sim_scores.argsort()[::-1][:buffer_size]

    results = []
    for idx in top_indices:
        if sim_scores[idx] <= 0:
            break
        row = _df.iloc[idx]
        stock = _stock_overrides.get(row["sku"], 0)
        if stock > 0:
            results.append(_row_to_catalog_item(row, stock))

    start = page * top_n
    return results[start:start + top_n]


def get_recommendations(sku: str, top_n: int = 7) -> list[CatalogItem]:
    """Similar products based on precomputed cosine similarity."""
    _ensure_loaded()
    if sku not in _sku_map:
        return []

    idx = _sku_map[sku]
    sim_scores = sorted(enumerate(_cosine_sim[idx]), key=lambda x: x[1], reverse=True)
    sim_scores = sim_scores[1:]  # skip self

    results = []
    for i, score in sim_scores:
        if len(results) >= top_n or score <= 0:
            break
        row = _df.iloc[i]
        stock = _stock_overrides.get(row["sku"], 0)
        if stock > 0:
            results.append(_row_to_catalog_item(row, stock))
    return results


def get_trending(top_n: int = 7) -> list[CatalogItem]:
    """Most popular products by rating * number of ratings."""
    _ensure_loaded()
    trending = _df[_df["no_of_ratings"] >= 50].copy()
    trending["popularity_score"] = trending["ratings"] * trending["no_of_ratings"]
    trending = trending.sort_values(by="popularity_score", ascending=False)

    results = []
    for _, row in trending.iterrows():
        if len(results) >= top_n:
            break
        stock = _stock_overrides.get(row["sku"], 0)
        if stock > 0:
            results.append(_row_to_catalog_item(row, stock))
    return results


def find_by_sku(sku: str) -> Optional[CatalogItem]:
    _ensure_loaded()
    if sku not in _sku_map:
        return None
    row = _df.iloc[_sku_map[sku]]
    return _row_to_catalog_item(row, _stock_overrides.get(sku, 0))


def decrement_stock(sku: str, qty: int) -> Optional[CatalogItem]:
    _ensure_loaded()
    with _lock:
        if sku in _stock_overrides:
            _stock_overrides[sku] = max(0, _stock_overrides[sku] - qty)
    return find_by_sku(sku)


def get_products_by_category(category: str, exclude_skus: set[str] | None = None, top_n: int = 10) -> list[CatalogItem]:
    """Fetch top products from a category, sorted by popularity."""
    _ensure_loaded()
    exclude = exclude_skus or set()
    filtered = _df[_df["category"] == category].copy()
    filtered["_score"] = filtered["ratings"] * filtered["no_of_ratings"]
    filtered = filtered.sort_values(by="_score", ascending=False)

    results = []
    for _, row in filtered.iterrows():
        if len(results) >= top_n:
            break
        if row["sku"] in exclude:
            continue
        stock = _stock_overrides.get(row["sku"], 0)
        if stock > 0:
            results.append(_row_to_catalog_item(row, stock))
    return results


def get_stock(sku: str) -> int:
    _ensure_loaded()
    return _stock_overrides.get(sku, 0)


def get_category(sku: str) -> Optional[str]:
    _ensure_loaded()
    if sku not in _sku_map:
        return None
    return str(_df.iloc[_sku_map[sku]]["category"])
