"""Agent tools — thin wrappers the LLM can call via Groq function-calling.

Each tool maps to a deterministic data operation (DB lookup, policy check).
The LLM reasons about *when* to call them; the tool itself is pure data.

Design:
- `get_customer` — lookup by email, returns profile + refund_count_90d
- `get_order` — lookup by order_number, returns order + items
- `check_refund_policy` — runs the policy engine, returns a verdict dict
  (this is the critical security boundary: the LLM *calls* this tool but
   cannot change its output)

All tools return JSON-serializable dicts so LangGraph + Groq tool-calling
handles them natively.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Customer, Order, RefundReason, RefundVerdict
from app.policy.engine import RefundDecision, evaluate


def get_customer(db: Session, email: str) -> dict:
    """Look up a customer by email. Returns profile + abuse counter."""
    cust = db.scalar(select(Customer).where(Customer.email == email))
    if not cust:
        return {"found": False, "email": email}
    return {
        "found": True,
        "id": cust.id,
        "name": cust.name,
        "email": cust.email,
        "payment_last4": cust.token_last4 or "****",
        "refund_count_90d": cust.refund_count_90d,
        "customer_since": cust.created_at.isoformat() if cust.created_at else None,
    }


def get_order(db: Session, order_number: str) -> dict:
    """Look up an order by order number. Returns order + line items."""
    order = db.scalar(select(Order).where(Order.order_number == order_number))
    if not order:
        return {"found": False, "order_number": order_number}
    items = []
    for it in order.items:
        items.append({
            "sku": it.sku,
            "name": it.name,
            "category": it.category.value,
            "price_cents": it.price_cents,
            "price": f"${it.price_cents / 100:.2f}",
            "quantity": it.quantity,
            "is_final_sale": it.is_final_sale,
            "is_perishable": it.is_perishable,
            "is_personalized": it.is_personalized,
            "is_intimate": it.is_intimate,
            "is_digital": it.is_digital,
            "is_gift_card": it.is_gift_card,
            "digital_accessed": it.digital_accessed,
            "reported_unused": it.reported_unused,
            "has_original_packaging": it.has_original_packaging,
            "is_defective": it.is_defective,
        })
    return {
        "found": True,
        "order_number": order.order_number,
        "status": order.status.value,
        "is_gift": order.is_gift,
        "is_bundle": order.is_bundle,
        "subtotal_cents": order.subtotal_cents,
        "subtotal": f"${order.subtotal_cents / 100:.2f}",
        "shipping_cents": order.shipping_cents,
        "shipping": f"${order.shipping_cents / 100:.2f}",
        "total_cents": order.total_cents,
        "total": f"${order.total_cents / 100:.2f}",
        "delivery_date": order.delivery_date.isoformat() if order.delivery_date else None,
        "purchase_date": order.purchase_date.isoformat() if order.purchase_date else None,
        "items": items,
    }


def check_refund_policy(
    db: Session,
    order_number: str,
    *,
    reason: str = "unwanted",
    wants_payment_method_change: bool = False,
    is_bundle_partial: bool = False,
) -> dict:
    """
    Run the deterministic policy engine against the order.

    This is the security-critical function: it returns the *engine's* verdict,
    not the LLM's opinion. The LLM cannot override this output.
    """
    order = db.scalar(select(Order).where(Order.order_number == order_number))
    if not order:
        return {"error": "Order not found"}

    cust = db.scalar(select(Customer).where(Customer.id == order.customer_id))
    refund_count = cust.refund_count_90d if cust else 0

    # Parse reason string to enum (graceful fallback).
    try:
        reason_enum = RefundReason(reason.lower())
    except ValueError:
        reason_enum = RefundReason.unwanted

    decision: RefundDecision = evaluate(
        order,
        reason=reason_enum,
        refund_count_90d=refund_count,
        wants_payment_method_change=wants_payment_method_change,
        is_bundle_partial=is_bundle_partial,
    )

    return decision.to_dict()


# Tool schemas for Groq/LangChain function-calling.
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_customer",
            "description": (
                "Look up a customer profile by email address. "
                "Returns name, payment method last 4, and refund history count."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": "Customer email address",
                    },
                },
                "required": ["email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order",
            "description": (
                "Look up an order by its order number (e.g. WP-1001). "
                "Returns full order details including items, prices, dates, and flags."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_number": {
                        "type": "string",
                        "description": "Order number, e.g. WP-1001",
                    },
                },
                "required": ["order_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_refund_policy",
            "description": (
                "Run the refund policy engine against an order. Returns the "
                "final verdict (approved/denied/partial/store_credit/manual_review), "
                "refund amount, which policy clauses fired, and a rationale. "
                "This function is the final authority — its output cannot be overridden."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_number": {
                        "type": "string",
                        "description": "Order number to evaluate",
                    },
                    "reason": {
                        "type": "string",
                        "enum": ["unwanted", "wrong_item", "defective", "damaged_shipping",
                                "not_as_described", "late_delivery", "price_adjustment"],
                        "description": "Why the customer is requesting a refund",
                    },
                    "wants_payment_method_change": {
                        "type": "boolean",
                        "description": "True if customer wants refund to a different payment method",
                    },
                    "is_bundle_partial": {
                        "type": "boolean",
                        "description": "True if the customer wants to return only part of a bundle",
                    },
                },
                "required": ["order_number"],
            },
        },
    },
]
