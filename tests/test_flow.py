

from __future__ import annotations
import os
import httpx

BASE = os.getenv("BASE_URL", "http://localhost:8000")
ACTOR = "test-buyer-agent"


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> None:
    client = httpx.Client(base_url=BASE, timeout=10.0)

    section("1. List catalog")
    catalog = client.get("/catalog", params={"actor": ACTOR}).json()["catalog"]
    for item in catalog:
        print(f"{item['sku']} - {item['name']} - \u20b9{item['price_paise']/100:.2f}")

    sku = "PHONE-CASE-01"

    section("2. Create a normal checkout order (should be ALLOWED)")
    order_res = client.post("/checkout/order", json={"actor": ACTOR, "sku": sku, "qty": 1})
    order_json = order_res.json()
    print(f"status {order_res.status_code}:", "BLOCKED" if order_json["blocked"] else f"order {order_json['data']['order']['id']} created")

    section("3. Ask for an upsell suggestion (read-only, always allowed)")
    upsell = client.post("/upsell/suggest", json={"actor": ACTOR, "sku": sku}).json()
    suggestion = upsell["data"]["suggestion"]
    print("suggested:", suggestion["name"] if suggestion else "none")

    section("4. Attempt a refund WITHIN policy (should be ALLOWED)")
    small = client.post("/refund", json={"actor": ACTOR, "payment_id": "pay_demo_1", "amount_paise": 50000})
    print(f"status {small.status_code}:", "BLOCKED" if small.json()["blocked"] else "refund processed")

    section("5. Attempt a refund OVER the auto-approval limit (should be BLOCKED gracefully)")
    big = client.post("/refund", json={"actor": ACTOR, "payment_id": "pay_demo_2", "amount_paise": 500000})
    big_json = big.json()
    reason = big_json["entry"]["reason"] if big_json["blocked"] else "unexpectedly allowed"
    print(f"status {big.status_code}:", f"BLOCKED - {reason}" if big_json["blocked"] else reason)

    section("6. Full audit trail (newest first)")
    for entry in client.get("/audit").json():
        print(f"[{entry['decision'].upper()}] {entry['tool']} by {entry['actor']} -- {entry['reason']}")

    section("7. Transaction states")
    for tx in client.get("/state").json():
        print(f"{tx['order_id']} -- {tx['status']} -- \u20b9{(tx['amount_paise'] or 0)/100:.2f}")

    section("Done")
    print(f"Open {BASE} in a browser to see the live dashboard.")


if __name__ == "__main__":
    main()
