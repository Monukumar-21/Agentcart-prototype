

from dotenv import load_dotenv
load_dotenv()

from mcp.server.fastmcp import FastMCP
from app import orchestrator

mcp = FastMCP("agentcart")

ACTOR = "mcp-agent" 


@mcp.tool()
def get_catalog() -> dict:
    """List the merchant's products with price, stock, and SKU."""
    return orchestrator.get_catalog(ACTOR).model_dump()


@mcp.tool()
def create_checkout_order(sku: str, qty: int = 1) -> dict:
    """Create a checkout order for a product. Gated: bounded by an
    auto-approval spending limit and a rate limit; every call is logged
    whether allowed or blocked.
    If successful, returns a payment_link. You MUST present this link to the user as a clickable markdown link like: [Pay Now](payment_link)."""
    return orchestrator.create_checkout_order(ACTOR, sku, qty).model_dump()


@mcp.tool()
def suggest_upsell(sku: str) -> dict:
    """Suggest a complementary product for a given SKU (read-only growth tool)."""
    return orchestrator.suggest_upsell(ACTOR, sku).model_dump()


@mcp.tool()
def refund_payment(payment_id: str, amount_paise: int) -> dict:
    """Refund a payment, amount in paise. Gated: amounts above the
    auto-approval limit are blocked and logged instead of executed."""
    return orchestrator.refund_payment(ACTOR, payment_id, amount_paise).model_dump()


@mcp.tool()
def get_audit_trail() -> list:
    """Return the full audit trail of every money action attempted so far,
    allowed or blocked, newest first."""
    return orchestrator.get_audit_trail()

@mcp.tool()
def get_campaign_stats() -> dict:
    """Get the current growth campaign performance stats (baseline vs agent-assisted attach rates)."""
    return orchestrator.get_campaign_stats(ACTOR).model_dump()


if __name__ == "__main__":
    mcp.run(transport="stdio")
