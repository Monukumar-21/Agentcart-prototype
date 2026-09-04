# AgentCart prototype

A working, testable version of the scoped AgentCart architecture

- **`app/main.py`** — a FastAPI REST API + a server-rendered dashboard
  (Jinja2 + a little vanilla JS to poll live data) you can click through
  in a browser.
- **`app/mcp_server.py`** — an MCP server over stdio, so an actual AI
  agent (Claude Desktop, Claude Code, etc.) can call the same tools
  directly.

Both call into the same orchestrator — so whichever front door is used,
the same guardrails, bounds, and audit log apply.

## Architecture -> files

| Diagram concept | File |
|---|---|
| Schema | `app/schema.py` — every request/decision/log shape, as Pydantic models |
| Guardrails | `app/guardrails.py` — is this request well-formed and sane |
| Policy engine | `app/policy_engine.py` — is this actor allowed to spend this much, this often |
| State manager | `app/state_manager.py` — transaction lifecycle + suspend-in-place |
| Error & retry tracing | `app/retry.py` — bounded retries, logged as audit traces |
| Audits / log manager | `app/audits.py` — append-only JSONL audit log |
| Orchestrator ("AI agent wrapper") | `app/orchestrator.py` — wires all of the above together |
| Razorpay integration | `app/razorpay_client.py` — real SDK, or a mock with the same shape |
| Merchant database | `app/catalog.py` — in-memory product catalog |

## 1. Setup

Requires Python 3.10+.

```bash
cd agentcart-python
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` ships with `MOCK_MODE=true`, so everything below works immediately
with **zero Razorpay signup**. The mock client mirrors the real SDK's
response shapes, so switching to live test-mode keys later needs no code
changes.

> Note: the `razorpay` package still imports the deprecated `pkg_resources`
> module, which prints a harmless `UserWarning` on newer `setuptools`.
> `requirements.txt` pins `setuptools<81` to avoid it entirely.

## 2. Run it

```bash
python -m app.main
# or: uvicorn app.main:app --reload
```

Open `http://localhost:8000` — a live dashboard: the catalog, a "try it"
panel to fire a checkout or a refund straight from the browser, the audit
trail, and the transaction state table, all polling every few seconds.

Run the scripted end-to-end test from a second terminal:

```bash
python tests/test_flow.py
```

This lists the catalog, creates a checkout order (allowed), asks for an
upsell suggestion, attempts a refund within policy (allowed), then
attempts a refund **over** the ₹2,000 auto-approval limit — which is
**blocked and logged with a plain-English reason**, not silently dropped
or crashed. That's the "one failure handled gracefully" requirement, made
concrete. Refresh the dashboard while it runs to watch it live.

You can also test by hand:

```bash
curl http://localhost:8000/catalog

curl -X POST http://localhost:8000/checkout/order \
  -H "Content-Type: application/json" \
  -d '{"actor":"me","sku":"PHONE-CASE-01","qty":1}'

curl -X POST http://localhost:8000/refund \
  -H "Content-Type: application/json" \
  -d '{"actor":"me","payment_id":"pay_fake","amount_paise":500000}'
```

### Trying the retry / error-tracing path

Set `MOCK_FAILURE_RATE=0.5` in `.env` (restart the server) to make the mock
Razorpay client randomly fail ~half the time. You'll see `retry_trace:*`
entries appear in the audit trail as it retries with backoff, and — if all
retries are exhausted — a clean `blocked` result instead of a crash.

## 3. Switch on real Razorpay test mode

1. Sign up / log in at [dashboard.razorpay.com](https://dashboard.razorpay.com).
2. **Settings → API Keys → Generate Test Key**. Copy the Key ID and Secret.
3. In `.env`:
   ```
   RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxx
   RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx
   MOCK_MODE=false
   ```
4. Restart. The dashboard header will say "(live Razorpay test mode)".

`POST /checkout/order` now creates a **real order** in your Razorpay test
dashboard (Payments → Orders — all test data, no real money moves). To
actually capture a payment against that order you need Razorpay's
client-side Checkout.js in a browser (card capture can't happen
server-side) — Razorpay's test cards (e.g. `4111 1111 1111 1111`, any
future expiry, any CVV) work there. This prototype covers the agent-facing
side end to end (create order, verify signature, refund); wiring up
Checkout.js on a real checkout page is the natural next step.

`POST /refund` calls the real Razorpay refund API against a real
`payment_id` — also fully simulated by Razorpay in test mode.

## 4. Test it as an actual MCP tool

**Quick check with the MCP Inspector** (Node's `npx`, no Claude setup
needed — the inspector itself is a Node tool even though the server is
Python):

```bash
npx @modelcontextprotocol/inspector .venv/bin/python -m app.mcp_server
```

This opens a local web UI where you can call `get_catalog`,
`create_checkout_order`, `suggest_upsell`, `refund_payment`, and
`get_audit_trail` directly and see the raw MCP request/response.

**Add it to Claude Desktop or Claude Code:**

```json
{
  "mcpServers": {
    "agentcart": {
      "command": "/absolute/path/to/agentcart-python/.venv/bin/python",
      "args": ["-m", "app.mcp_server"],
      "cwd": "/absolute/path/to/agentcart-python"
    }
  }
}
```

Then ask an agent: *"Check the AgentCart catalog and buy a phone case,
then try to refund ₹5000 on a fake payment and tell me what happens."*
You'll see the checkout succeed and the oversized refund come back
blocked with a clear reason — then check `GET /audit` or the dashboard to
see both logged.


## Known limitations (be upfront about these in a demo)

- Catalog, state, and rate-limit counters are in-memory and reset on
  restart — fine for a demo, not a production merchant DB integration.
- `verify_signature` does a real HMAC check once live keys are set, but
  there's no browser checkout page included — payment capture itself has
  to happen client-side with Razorpay Checkout.js.
- The audit log is a local JSONL file — for production, swap in a real
  store (Postgres, etc.) behind the same `AuditLogger` interface.
- Only one "actor" identity model (a string) — a real deployment would
  authenticate each calling agent (API key, OAuth) rather than trust a
  self-reported name.
