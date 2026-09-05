"""
Upsell engine — suggests complementary products at checkout.

Uses a cross-sell category map (phone -> charger, case, earbuds, etc.)
and a tiered discount system based on addon price vs cart total:
  < 10% of cart  -> no discount
  10-30%         -> 10% off
  30-50%         -> 15% off
  > 50%          -> 20% off
"""

from __future__ import annotations

from typing import Optional
from app import recommendation_engine
from app.schema import CatalogItem, UpsellSuggestion

# what to suggest when cart contains items from each category
_CROSS_SELL_MAP: dict[str, list[tuple[str, str]]] = {
    "phone": [
        ("charger", "Essential charger for your phone"),
        ("cable", "Charging cable for your new phone"),
        ("case", "Protect your phone with a case"),
        ("screen_guard", "Keep your screen scratch-free"),
        ("earbuds", "Great earbuds to pair with your phone"),
        ("neckband", "Wireless neckband for hands-free calls"),
        ("power_bank", "Stay charged on the go"),
    ],
    "laptop": [
        ("mouse", "A mouse for better productivity"),
        ("keyboard", "Upgrade your typing experience"),
        ("stand", "Ergonomic laptop stand for comfort"),
        ("bag", "Carry your laptop safely"),
        ("hub", "Expand your laptop's ports"),
        ("cleaning", "Keep your laptop screen clean"),
    ],
    "earbuds": [
        ("case", "Protective case for your earbuds"),
        ("cable", "Spare charging cable"),
        ("power_bank", "Keep your earbuds charged on the go"),
    ],
    "headphones": [
        ("stand", "Display your headphones in style"),
        ("cable", "Replacement audio cable"),
        ("cleaning", "Keep your headphones fresh"),
    ],
    "neckband": [
        ("case", "Carry pouch for your neckband"),
        ("power_bank", "Portable charger for your neckband"),
    ],
    "smartwatch": [
        ("charger", "Charger for your smartwatch"),
        ("screen_guard", "Protect your watch face"),
        ("strap", "Switch up your watch style"),
    ],
    "camera": [
        ("memory_card", "Extra storage for your shots"),
        ("tripod", "Steady your camera for perfect photos"),
        ("bag", "Protect your camera on the go"),
        ("cleaning", "Keep your lens spotless"),
    ],
    "tv": [
        ("speaker", "Enhance your TV audio"),
        ("cable", "HDMI cable for your setup"),
        ("stand", "Wall mount or TV stand"),
    ],
    "tablet": [
        ("case", "Protect your tablet"),
        ("charger", "Fast charger for your tablet"),
        ("keyboard", "Turn your tablet into a workstation"),
    ],
    "speaker": [
        ("cable", "Audio cable for your speaker"),
        ("stand", "Speaker stand for better placement"),
    ],
    "power_bank": [
        ("cable", "Charging cable for your power bank"),
    ],
    "charger": [
        ("cable", "Matching cable for your charger"),
    ],
    "mouse": [
        ("keyboard", "Complete your desk setup"),
        ("stand", "Mouse pad or desk mat"),
    ],
    "keyboard": [
        ("mouse", "Matching mouse for your keyboard"),
        ("cleaning", "Keep your keyboard clean"),
    ],
}


def _calculate_discount_percent(addon_price: float, cart_total: float) -> float:
    """Tiered discount based on how much the addon costs relative to the cart."""
    if cart_total <= 0:
        return 0.0
    ratio = addon_price / cart_total
    if ratio < 0.10:
        return 0.0
    elif ratio < 0.30:
        return 10.0
    elif ratio < 0.50:
        return 15.0
    else:
        return 20.0


def get_upsell_suggestions(
    cart_skus: dict[str, int],
    cart_total_rupees: float,
    top_n: int = 5,
) -> list[UpsellSuggestion]:
    """
    Find complementary products for items in the cart.
    Skips items already in the cart, out-of-stock products,
    and items that cost more than the cart total (addons should be cheaper).
    """
    if not cart_skus:
        return []

    # figure out what categories are already in the cart
    cart_categories: set[str] = set()
    existing_skus: set[str] = set(cart_skus.keys())

    for sku in cart_skus:
        cat = recommendation_engine.get_category(sku)
        if cat:
            cart_categories.add(cat)

    seen_categories: set[str] = set()
    suggestions: list[UpsellSuggestion] = []

    for cart_cat in cart_categories:
        cross_sells = _CROSS_SELL_MAP.get(cart_cat, [])
        for target_cat, reason in cross_sells:
            # skip if we already suggested from this category
            if target_cat in seen_categories:
                continue
            # skip if user already has something from this category
            if target_cat in cart_categories:
                continue
            seen_categories.add(target_cat)

            products = recommendation_engine.get_products_by_category(
                target_cat, exclude_skus=existing_skus, top_n=10
            )

            for product in products:
                if len(suggestions) >= top_n:
                    break
                if product.stock <= 0:
                    continue
                # Only suggest addons that cost less than the cart total
                if product.price_rupees >= cart_total_rupees:
                    continue

                discount_pct = _calculate_discount_percent(product.price_rupees, cart_total_rupees)
                discounted_price = None
                if discount_pct > 0:
                    discounted_price = round(product.price_rupees * (1 - discount_pct / 100), 2)

                suggestions.append(UpsellSuggestion(
                    product=product,
                    reason=reason,
                    discount_percent=discount_pct,
                    discounted_price_rupees=discounted_price,
                ))

            if len(suggestions) >= top_n:
                break

    return suggestions[:top_n]


def calculate_bundle_discount(addon_price_rupees: float, cart_total_rupees: float) -> dict:
    """What discount would this addon get if added to a cart of this total?"""
    discount_pct = _calculate_discount_percent(addon_price_rupees, cart_total_rupees)
    discounted_price = None
    savings = 0.0
    if discount_pct > 0:
        discounted_price = round(addon_price_rupees * (1 - discount_pct / 100), 2)
        savings = round(addon_price_rupees - discounted_price, 2)

    return {
        "original_price_rupees": addon_price_rupees,
        "discount_percent": discount_pct,
        "discounted_price_rupees": discounted_price,
        "savings_rupees": savings,
        "has_discount": discount_pct > 0,
    }


def get_cart_pricing(cart_skus: dict[str, int]) -> dict:
    from app import recommendation_engine
    items = []
    for sku, qty in cart_skus.items():
        product = recommendation_engine.find_by_sku(sku)
        if product:
            cat = recommendation_engine.get_category(sku)
            items.append({"sku": sku, "qty": qty, "product": product, "cat": cat})
    
    items.sort(key=lambda x: x["product"].price_rupees, reverse=True)
    
    cart_total = 0.0
    primary_categories = set()
    result_items = []
    
    for item in items:
        is_addon = False
        for pcat in primary_categories:
            if any(target == item["cat"] for target, _ in _CROSS_SELL_MAP.get(pcat, [])):
                is_addon = True
                break
                
        price = item["product"].price_rupees
        discount_pct = 0.0
        final_price = price
        
        if is_addon:
            discount_pct = _calculate_discount_percent(price, cart_total)
            if discount_pct > 0:
                final_price = round(price * (1 - discount_pct / 100), 2)
        else:
            if item["cat"]:
                primary_categories.add(item["cat"])
            
        item_total = final_price * item["qty"]
        cart_total += item_total
        
        result_items.append({
            "sku": item["sku"],
            "name": item["product"].name,
            "image_url": item["product"].image_url,
            "qty": item["qty"],
            "original_price_rupees": price,
            "final_price_rupees": final_price,
            "discount_percent": discount_pct,
            "subtotal_rupees": item_total,
        })
        
    return {"total_rupees": round(cart_total, 2), "items": result_items}
