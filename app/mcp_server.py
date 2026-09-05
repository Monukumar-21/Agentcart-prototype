

from dotenv import load_dotenv
load_dotenv()

from mcp.server.fastmcp import FastMCP
from app import orchestrator, razorpay_client

mcp = FastMCP("agentcart")

ACTOR = "mcp-agent" 


def _format_product_markdown(product: dict) -> str:
    """Format a product dict as rich markdown with image for chat display.
    
    IMPORTANT: The image_url MUST be rendered as a markdown image so the user
    can see the product photo directly in the chat.
    """
    lines = []
    name = product.get("name", "Unknown")
    image_url = product.get("image_url", "")
    price = product.get("price_rupees", 0.0)
    actual_price = product.get("actual_price_rupees", 0.0)
    sku = product.get("sku", "")
    ratings = product.get("ratings")
    stock = product.get("stock", 0)
    category = product.get("category", "")
    
    lines.append(f"**{name}**")
    if actual_price > price and actual_price > 0:
        lines.append(f"💰 ~~₹{actual_price:,.0f}~~ **₹{price:,.0f}**")
    else:
        lines.append(f"💰 **₹{price:,.0f}**")
    if ratings and ratings > 0:
        lines.append(f"⭐ {ratings}/5")
    lines.append(f"📦 SKU: `{sku}` | Stock: {stock} | Category: {category}")
    if image_url:
        lines.append(f"\nProduct image: {image_url}")
    return "\n".join(lines)


def _format_product_with_image(product: dict) -> str:
    """Format a product with its image URL prominently included."""
    name = product.get("name", "Unknown")
    image_url = product.get("image_url", "")
    price = product.get("price_rupees", 0.0)
    actual_price = product.get("actual_price_rupees", 0.0)
    sku = product.get("sku", "")
    ratings = product.get("ratings")
    stock = product.get("stock", 0)
    category = product.get("category", "")
    
    parts = [f"**{name}**"]
    if actual_price > price and actual_price > 0:
        parts.append(f"Price: ~~₹{actual_price:,.0f}~~ **₹{price:,.0f}**")
    else:
        parts.append(f"Price: **₹{price:,.0f}**")
    if ratings and ratings > 0:
        parts.append(f"Rating: ⭐ {ratings}/5")
    parts.append(f"SKU: `{sku}` | Stock: {stock} | Category: {category}")
    if image_url:
        parts.append(f"Image URL: {image_url}")
    return "\n".join(parts)


@mcp.tool()
def search_products(query: str, top_n: int = 7, page: int = 0) -> str:
    """Search for products by name/description. Returns product cards with images, prices, and SKUs.
    Use page parameter to see next results (page 0 = first 7, page 1 = next 7, etc.).
    
    IMPORTANT: When presenting results to the user, you MUST include the product image URLs
    so the user can see what the products look like. Display each product's image_url as a 
    clickable link or embedded image."""
    result = orchestrator.search_products(ACTOR, query=query, top_n=top_n, page=page)
    data = result.data
    if not data or not data.get("products"):
        return f"No products found for '{query}'. This catalog focuses on electronics. Try searching for phones, laptops, earbuds, or accessories instead!"
    
    products = data["products"]
    output = [f"## 🔍 Search results for \"{query}\" (page {page + 1}, showing {len(products)} items)\n"]
    for i, p in enumerate(products, 1):
        output.append(f"### {i}. {_format_product_with_image(p)}")
        output.append("")  # blank line
    
    if len(products) == top_n:
        output.append(f"\n📄 *More results may be available. Use `page={page + 1}` to see next items.*")
    
    return "\n".join(output)


@mcp.tool()
def get_product_details(sku: str) -> str:
    """Get detailed information about a specific product by SKU, including its image URL.
    
    IMPORTANT: You MUST show the product's image_url to the user so they can see the product photo.
    If the product has an image_url, present it prominently."""
    from app import catalog
    item = catalog.find_by_sku(sku)
    if not item:
        return f"Product with SKU `{sku}` not found."
    return _format_product_with_image(item.model_dump())


@mcp.tool()
def get_recommendations(sku: str, top_n: int = 7) -> str:
    """Get similar product recommendations for a given SKU. Shows products with images.
    
    IMPORTANT: Include each product's image_url in your response so the user can see the products."""
    result = orchestrator.get_recommendations(ACTOR, sku=sku, top_n=top_n)
    data = result.data
    if not data or not data.get("recommendations"):
        return f"No recommendations found for SKU `{sku}`."
    
    products = data["recommendations"]
    output = [f"## 🎯 Similar products to `{sku}` ({len(products)} found)\n"]
    for i, p in enumerate(products, 1):
        output.append(f"### {i}. {_format_product_with_image(p)}")
        output.append("")
    return "\n".join(output)


@mcp.tool()
def get_trending(top_n: int = 7) -> str:
    """Get trending/popular products right now. Shows product cards with images.
    
    IMPORTANT: Include each product's image_url in your response so the user can see the products."""
    result = orchestrator.get_trending(ACTOR, top_n=top_n)
    data = result.data
    if not data or not data.get("trending"):
        return "No trending products available."
    
    products = data["trending"]
    output = [f"## 🔥 Trending Products ({len(products)} items)\n"]
    for i, p in enumerate(products, 1):
        output.append(f"### {i}. {_format_product_with_image(p)}")
        output.append("")
    return "\n".join(output)


@mcp.tool()
def add_to_cart(sku: str, qty: int = 1) -> dict:
    """Add a product to the cart. Validates stock and boundaries."""
    return orchestrator.add_to_cart(ACTOR, sku, qty).model_dump()


@mcp.tool()
def remove_from_cart(sku: str, qty: int = 1) -> dict:
    """Remove a specific quantity of a product from the cart."""
    return orchestrator.remove_from_cart(ACTOR, sku, qty).model_dump()


@mcp.tool()
def view_cart() -> str:
    """View the current contents of your cart with product details and images.
    
    IMPORTANT: Include each product's image_url in your response."""
    result = orchestrator.get_current_cart(ACTOR)
    cart_data = result.data.get("cart", {})
    if not cart_data:
        return "🛒 Your cart is empty."
    
    from app import catalog
    output = ["## 🛒 Your Cart\n"]
    total = 0
    for sku, qty in cart_data.items():
        item = catalog.find_by_sku(sku)
        if item:
            subtotal = item.price_rupees * qty
            total += subtotal
            output.append(f"- **{item.name}** × {qty} = ₹{subtotal:,.2f}")
            if item.image_url:
                output.append(f"  Image: {item.image_url}")
            output.append(f"  SKU: `{sku}`")
            output.append("")
    
    output.append(f"\n**Cart Total: ₹{total:,.2f}**")
    return "\n".join(output)


@mcp.tool()
def checkout_cart(skip_upsell: bool = False) -> str:
    """Checkout the cart. This tool has a BUILT-IN upsell agent that automatically suggests 
    complementary products with discounts BEFORE completing checkout.
    
    Flow:
    1. First call: Automatically shows smart upsell suggestions (cross-sell items with discounts).
       Present these suggestions to the user and ask if they want to add anything.
    2. Second call with skip_upsell=True: Proceeds to actual checkout and auto-completes payment.
    
    IMPORTANT: When calling this for the first time, ALWAYS leave skip_upsell=False (default) 
    so the upsell agent can suggest money-saving add-ons to the user. Only set skip_upsell=True 
    after the user has seen the suggestions and wants to proceed with checkout."""
    
    current_cart = orchestrator.get_current_cart(ACTOR)
    cart_data = current_cart.data.get("cart", {})
    if not cart_data:
        return "🛒 Your cart is empty. Add items before checking out."

    # ── Step 1: Upsell Agent ──────────────────────────────────────────────────
    if not skip_upsell:
        upsell_result = orchestrator.suggest_upsell(ACTOR)
        suggestions = upsell_result.data.get("suggestions", [])
        cart_total = upsell_result.data.get("cart_total_rupees", 0.0)
        
        output = [f"## 🛒 Pre-Checkout Review (Cart Total: ₹{cart_total:,.2f})\n"]
        
        # Show cart contents
        from app import catalog
        output.append("**Your items:**")
        for sku, qty in cart_data.items():
            item = catalog.find_by_sku(sku)
            if item:
                output.append(f"- {item.name} × {qty} = ₹{item.price_rupees * qty:,.2f}")
        output.append("")
        
        if suggestions:
            output.append("---")
            output.append("## 💡 Smart Suggestions — Save more with these add-ons!\n")
            
            for i, s in enumerate(suggestions, 1):
                product = s["product"]
                reason = s["reason"]
                discount_pct = s["discount_percent"]
                discounted_price = s.get("discounted_price_rupees")
                
                output.append(f"**{i}. {product['name']}**")
                
                price = product["price_rupees"]
                if discount_pct > 0 and discounted_price:
                    savings = price - discounted_price
                    output.append(f"   💰 ~~₹{price:,.0f}~~ **₹{discounted_price:,.0f}** ({discount_pct:.0f}% off — save ₹{savings:,.0f}!)")
                else:
                    output.append(f"   💰 ₹{price:,.0f}")
                output.append(f"   📌 {reason}")
                output.append(f"   SKU: `{product['sku']}`")
                if product.get("image_url"):
                    output.append(f"   Image: {product['image_url']}")
                output.append("")
            
            output.append("🛒 **Would you like to add any of these to your cart?**")
            output.append("Say which items to add, or say 'no thanks, just checkout' to proceed without them.")
        else:
            output.append("✅ No additional suggestions for your cart.")
            output.append("\nReady to proceed with checkout? Say 'yes' to confirm.")
        
        return "\n".join(output)

    # ── Step 2: Actual Checkout ───────────────────────────────────────────────
    result = orchestrator.checkout_cart(ACTOR)
    
    if result.blocked:
        reason = result.entry.reason if result.entry else "Unknown reason"
        return f"❌ Checkout was blocked: {reason}"
    
    order = result.data.get("order", {})
    order_id = order.get("id", "")
    amount = order.get("amount", 0)  # This is in paise from Razorpay
    
    # Auto-complete payment in mock mode (no server needed for payment page)
    if razorpay_client.MOCK_MODE:
        verify_result = orchestrator.verify_payment(
            ACTOR, order_id, f"pay_mock_{order_id}", "mock_auto_signature"
        )
        
        output = [
            "## ✅ Order Complete!\n",
            f"**Order ID:** `{order_id}`",
            f"**Amount:** ₹{amount / 100:,.2f}",
            f"**Status:** Payment successful (auto-completed in mock mode)",
            f"\n🎉 Your order has been placed successfully!",
        ]
        return "\n".join(output)
    else:
        # Live mode — return the payment link
        payment_link = result.data.get("payment_link", "")
        output = [
            "## 🛒 Order Created!\n",
            f"**Order ID:** `{order_id}`",
            f"**Amount:** ₹{amount / 100:,.2f}",
            f"\n**⚠️ The FastAPI server must be running for the payment page to work.**",
            f"Make sure `python -m app.main` is running, then click:",
            f"\n[💳 Pay Now]({payment_link})",
        ]
        return "\n".join(output)


@mcp.tool()
def suggest_upsell(sku: str = None) -> str:
    """Get smart cross-sell suggestions for items in your cart. Shows complementary products 
    with images and potential bundle discounts.
    
    NOTE: You usually don't need to call this directly — the checkout_cart tool automatically 
    runs the upsell agent. Use this only if the user explicitly asks for suggestions without 
    wanting to checkout yet."""
    result = orchestrator.suggest_upsell(ACTOR, sku)
    data = result.data
    if not data or not data.get("suggestions"):
        return "No upsell suggestions available for your current cart."
    
    suggestions = data["suggestions"]
    cart_total = data.get("cart_total_rupees", 0.0)
    output = [f"## 💡 Recommended Add-ons (Cart total: ₹{cart_total:,.2f})\n"]
    
    for i, s in enumerate(suggestions, 1):
        product = s["product"]
        reason = s["reason"]
        discount_pct = s["discount_percent"]
        discounted_price = s.get("discounted_price_rupees")
        
        output.append(f"### {i}. {product['name']}")
        
        price = product["price_rupees"]
        if discount_pct > 0 and discounted_price:
            savings = price - discounted_price
            output.append(f"💰 ~~₹{price:,.2f}~~ **₹{discounted_price:,.2f}** ({discount_pct:.0f}% off — save ₹{savings:,.2f}!)")
        else:
            output.append(f"💰 **₹{price:,.2f}**")
        
        output.append(f"📌 *{reason}*")
        output.append(f"📦 SKU: `{product['sku']}`")
        if product.get("image_url"):
            output.append(f"Image: {product['image_url']}")
        output.append("")
    
    output.append("\n*Add any of these to your cart with `add_to_cart(sku)` before checkout!*")
    return "\n".join(output)


@mcp.tool()
def refund_payment(payment_id: str, amount_rupees: float) -> dict:
    """Refund a payment, amount in rupees. Gated: amounts above the
    auto-approval limit are blocked and logged instead of executed."""
    return orchestrator.refund_payment(ACTOR, payment_id, amount_rupees).model_dump()


@mcp.tool()
def simulate_payment_success(order_id: str, payment_id: str = "pay_mock_123", signature: str = "mock_sig") -> dict:
    """Simulate a successful payment for an order (for testing in chat without browser).
    NOTE: You usually don't need this — checkout_cart already auto-completes payment in mock mode."""
    return orchestrator.verify_payment(ACTOR, order_id, payment_id, signature).model_dump()


@mcp.tool()
def get_audit_trail() -> list:
    """Return the full audit trail of every money action attempted so far,
    allowed or blocked, newest first."""
    return orchestrator.get_audit_trail()

@mcp.tool()
def get_campaign_stats() -> dict:
    """Get the current growth campaign performance stats (baseline vs agent-assisted attach rates)."""
    return orchestrator.get_campaign_stats(ACTOR).model_dump()


@mcp.tool()
def get_settings() -> dict:
    """Get the current guardrail and policy settings (e.g. max auto-approval limits)."""
    return orchestrator.get_settings(ACTOR).model_dump()


@mcp.tool()
def update_settings(max_auto_approve_rupees: float, max_actions_per_minute: int, max_qty_per_order: int, blocked_actors: list[str]) -> dict:
    """Customize the guardrail and policy settings dynamically."""
    return orchestrator.update_settings(ACTOR, max_auto_approve_rupees, max_actions_per_minute, max_qty_per_order, blocked_actors).model_dump()


if __name__ == "__main__":
    mcp.run(transport="stdio")
