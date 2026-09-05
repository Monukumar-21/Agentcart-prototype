"""
End-to-end test — runs through search, cart, checkout, upsell, and refund flows
against a running server. Start the server first: python -m app.main
"""

from __future__ import annotations
import os
import httpx

BASE = os.getenv("BASE_URL", "http://localhost:8000")
ACTOR = "test-buyer-agent"


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> None:
    client = httpx.Client(base_url=BASE, timeout=10.0)

    section("1. Search for products")
    results = client.get("/catalog/search", params={"q": "earbuds", "top_n": 3}).json()
    products = results.get("products", [])
    for item in products:
        print(f"  {item['sku']} - {item['name']} - ₹{item['price_rupees']:.2f}")

    if not products:
        print("  No products found, using trending instead")
        trending = client.get("/catalog/trending", params={"top_n": 3}).json()
        products = trending.get("trending", [])
        for item in products:
            print(f"  {item['sku']} - {item['name']} - ₹{item['price_rupees']:.2f}")

    sku = products[0]["sku"] if products else "AMZN-0001"

    section("2. Add to cart and checkout")
    client.post("/cart", json={"actor": ACTOR, "sku": sku, "qty": 1})
    order_res = client.post("/checkout/cart", json={"actor": ACTOR})
    order_json = order_res.json()
    if order_json["blocked"]:
        print(f"  BLOCKED: {order_json['entry']['reason']}")
    else:
        print(f"  Order created: {order_json['data']['order']['id']}")

    section("3. Upsell suggestions")
    # add item back for upsell test
    client.post("/cart", json={"actor": ACTOR, "sku": sku, "qty": 1})
    upsell = client.post("/upsell/suggest", json={"actor": ACTOR, "sku": sku}).json()
    suggestions = upsell.get("data", {}).get("suggestions", [])
    if suggestions:
        for s in suggestions:
            name = s["product"]["name"]
            disc = f" ({s['discount_percent']:.0f}% off)" if s["discount_percent"] > 0 else ""
            print(f"  → {name}{disc} — {s['reason']}")
    else:
        print("  No suggestions")

    section("4. Refund (Should block if order is not paid)")
    if not order_json.get("blocked"):
        order_id = order_json["data"]["order"]["id"]
        res = client.post("/refund", json={"actor": ACTOR, "order_id": order_id, "sku": sku, "qty": 1})
        res_json = res.json()
        print(f"  Status {res.status_code}: {'BLOCKED' if res_json['blocked'] else 'refund processed'} - {res_json.get('entry', {}).get('reason', '')}")
    else:
        print("  Skipping refund because checkout was blocked.")

    section("6. Audit trail (last 5)")
    for entry in client.get("/audit").json()[:5]:
        print(f"  [{entry['decision'].upper()}] {entry['tool']} by {entry['actor']} — {entry['reason']}")

    section("7. Transaction states")
    for tx in client.get("/state").json():
        amt = f"₹{tx['amount_rupees']:.2f}" if tx.get("amount_rupees") else "—"
        print(f"  {tx['order_id']} — {tx['status']} — {amt}")

    section("Done")
    print(f"Open {BASE} in a browser to see the dashboard.")


if __name__ == "__main__":
    main()
