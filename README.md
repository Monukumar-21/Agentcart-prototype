# AgentCart

An AI-powered shopping cart prototype with built-in guardrails, recommendations, and upsell logic.

Two entry points, same backend:

- **`app/main.py`** — FastAPI REST API + web dashboard you can use from a browser
- **`app/mcp_server.py`** — MCP server (stdio) for AI agents like Claude Desktop

Both go through the same orchestrator, so the same guardrails, spending limits, and audit trail apply regardless of how the system is accessed.

## What it does

- **Product search** over ~8,700 Amazon products using TF-IDF similarity matching
- **Smart upsell agent** that suggests complementary products at checkout with tiered discounts (10-20% based on addon/cart price ratio)
- **Content-based recommendations** via cosine similarity
- **Cart + checkout flow** with Razorpay integration (mock or live)
- **Guardrails everywhere** — spending limits, rate limiting, stock checks, actor blocklists
- **Full audit trail** — every action (allowed or blocked) gets logged to `data/audit.log`

## Architecture

| What it does | Where it lives |
|---|---|
| Data models | `app/schema.py` — Pydantic models for every request, response, and log entry |
| Product data | `app/recommendation_engine.py` — loads CSV, builds TF-IDF index, handles search/recommendations |
| Upsell logic | `app/upsell_engine.py` — cross-sell mapping + tiered discount calculations |
| Catalog API | `app/catalog.py` — thin wrapper over the recommendation engine |
| Input validation | `app/guardrails.py` — checks stock, SKU validity, actor blocklists, refund ceilings |
| Spending policy | `app/policy_engine.py` — auto-approval limits, rate limiting per actor |
| Transaction state | `app/state_manager.py` — order lifecycle tracking with suspend-in-place |
| Retry logic | `app/retry.py` — bounded retries with backoff, each attempt logged |
| Audit log | `app/audits.py` — append-only JSONL log |
| Orchestrator | `app/orchestrator.py` — wires everything together |
| Payment | `app/razorpay_client.py` — Razorpay SDK wrapper with mock fallback |
| Per-actor carts | `app/cart.py` — in-memory cart storage keyed by actor |

## Setup

Requires Python 3.10+.

```bash
cd agentcart-python
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

The default `.env` has `MOCK_MODE=true`, so everything works out of the box without Razorpay credentials. The mock client returns the same response shapes as the real SDK.

> Note: the `razorpay` package uses `pkg_resources` internally, which can print
> a harmless `UserWarning` on newer setuptools. `requirements.txt` pins
> `setuptools<81` to suppress it.

## Run it

```bash
python -m app.main
# or: uvicorn app.main:app --reload
```

Open `http://localhost:8000` — the dashboard has product search, a cart, upsell suggestions panel, checkout flow, audit trail, and settings.

### Quick test

```bash
# search for products
curl "http://localhost:8000/catalog/search?q=phone&top_n=3"

# add to cart
curl -X POST http://localhost:8000/cart \
  -H "Content-Type: application/json" \
  -d '{"actor":"test","sku":"AMZN-0001","qty":1}'

# get upsell suggestions
curl -X POST http://localhost:8000/upsell/suggest \
  -H "Content-Type: application/json" \
  -d '{"actor":"test"}'

# checkout
curl -X POST http://localhost:8000/checkout/cart \
  -H "Content-Type: application/json" \
  -d '{"actor":"test"}'

# try a refund over the limit (gets blocked gracefully)
curl -X POST http://localhost:8000/refund \
  -H "Content-Type: application/json" \
  -d '{"actor":"test","payment_id":"pay_fake","amount_rupees":5000}'
```

There's also a scripted test:
```bash
python tests/test_flow.py
```

### Testing retry/failure paths

Set `MOCK_FAILURE_RATE=0.5` in `.env` and restart. The mock Razorpay client will randomly fail about half the time — you'll see retry entries in the audit trail and graceful blocked responses instead of crashes.

## Razorpay live mode

1. Get test keys from [dashboard.razorpay.com](https://dashboard.razorpay.com) → Settings → API Keys
2. Update `.env`:
   ```
   RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxx
   RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx
   MOCK_MODE=false
   ```
3. Restart. The dashboard header will switch to "LIVE RAZORPAY".

## MCP integration (Claude Desktop / Claude Code)

Test with the MCP Inspector:
```bash
npx @modelcontextprotocol/inspector venv/bin/python -m app.mcp_server
```

Add to Claude Desktop config:
```json
{
  "mcpServers": {
    "agentcart": {
      "command": "/path/to/agentcart-python/venv/bin/python",
      "args": ["-m", "app.mcp_server"],
      "cwd": "/path/to/agentcart-python"
    }
  }
}
```

Then just chat: *"Search for earbuds under ₹2000"* or *"Add a phone case to my cart and check out"*.

The checkout tool has a built-in upsell agent — it'll automatically suggest add-ons with discounts before completing the order.

## Known limitations

- Everything is in-memory (catalog, carts, transactions) — resets on restart
- Actor identity is just a string — no real auth
- Audit log is a local JSONL file — swap in a database for production
