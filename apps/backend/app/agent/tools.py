"""Agent tools and validation for the dynamic LangGraph loop.

The LLM decides *which* tool to call. This module decides whether that call is
safe, normalized, and allowed. The deterministic policy engine remains the
authority: action tools can only be executed after ``check_refund_policy`` has
already produced a verdict in the current trace.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Customer, Order, RefundReason
from app.policy.engine import RefundDecision, evaluate
from app.security.injection_guard import check_injection


EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.I)
ORDER_RE = re.compile(r"^WP-\d{4}$", re.I)
ORDER_CANDIDATE_RE = re.compile(r"\bWP\s*-?\s*(\d{4})\b", re.I)
REFUND_REASONS = {
    "unwanted",
    "wrong_item",
    "defective",
    "damaged_shipping",
    "not_as_described",
    "late_delivery",
    "price_adjustment",
}


@dataclass
class ToolValidationError(Exception):
    """A safe, customer-independent error returned to the agent loop."""

    code: str
    message: str
    suggested_args: dict[str, Any] = field(default_factory=dict)


def _iter_string_args(value: Any, path: str = "") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(path, value)]
    if isinstance(value, dict):
        strings: list[tuple[str, str]] = []
        for key, nested in value.items():
            child = f"{path}.{key}" if path else str(key)
            strings.extend(_iter_string_args(nested, child))
        return strings
    if isinstance(value, list):
        strings = []
        for index, nested in enumerate(value):
            child = f"{path}[{index}]"
            strings.extend(_iter_string_args(nested, child))
        return strings
    return []


def _reject_injection(args: dict[str, Any]) -> None:
    for path, text in _iter_string_args(args):
        blocked, pattern = check_injection(text)
        if blocked:
            raise ToolValidationError(
                code="prompt_injection_tool_arg",
                message=f"Rejected unsafe tool argument at {path or 'value'}.",
                suggested_args={"matched_pattern": pattern},
            )


def normalize_order_number(value: str) -> str:
    raw = value.strip().upper()
    if ORDER_RE.fullmatch(raw):
        return raw

    candidate = ORDER_CANDIDATE_RE.search(raw)
    if candidate:
        normalized = f"WP-{candidate.group(1)}"
        raise ToolValidationError(
            code="malformed_order_number",
            message=f"Order number '{value}' is malformed.",
            suggested_args={"order_number": normalized},
        )

    raise ToolValidationError(
        code="invalid_order_number",
        message="Order number must use the format WP-1001.",
    )


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if not EMAIL_RE.fullmatch(email):
        raise ToolValidationError(
            code="invalid_email",
            message="Email address is not valid.",
        )
    return email


def normalize_reason(value: str | None) -> str:
    reason = (value or "unwanted").strip().lower()
    if reason not in REFUND_REASONS:
        return "unwanted"
    return reason


def validate_tool_args(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize arguments before any DB/policy access."""
    args = dict(args or {})
    _reject_injection(args)

    if tool_name == "get_customer":
        if not args.get("email"):
            raise ToolValidationError("missing_email", "get_customer requires an email.")
        return {"email": normalize_email(str(args["email"]))}

    if tool_name == "get_order":
        if not args.get("order_number"):
            raise ToolValidationError("missing_order_number", "get_order requires an order number.")
        return {"order_number": normalize_order_number(str(args["order_number"]))}

    if tool_name == "check_refund_policy":
        if not args.get("order_number"):
            raise ToolValidationError(
                "missing_order_number",
                "check_refund_policy requires an order number.",
            )
        return {
            "order_number": normalize_order_number(str(args["order_number"])),
            "reason": normalize_reason(args.get("reason")),
            "wants_payment_method_change": bool(args.get("wants_payment_method_change", False)),
            "is_bundle_partial": bool(args.get("is_bundle_partial", False)),
        }

    if tool_name in {"process_refund", "deny_refund", "flag_for_escalation"}:
        if not args.get("order_number"):
            raise ToolValidationError(
                "missing_order_number",
                f"{tool_name} requires an order number.",
            )
        normalized: dict[str, Any] = {
            "order_number": normalize_order_number(str(args["order_number"])),
            "reason": normalize_reason(args.get("reason")),
        }
        if "refund_cents" in args:
            normalized["refund_cents"] = max(0, int(args["refund_cents"]))
        if "message" in args:
            normalized["message"] = str(args["message"]).strip()[:500]
        return normalized

    raise ToolValidationError("unknown_tool", f"Unknown tool: {tool_name}")


def get_customer(db: Session, email: str) -> dict:
    """Look up a customer by email. Returns profile plus abuse counter."""
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


def get_order(db: Session, order_number: str, *, for_customer_id: int | None = None) -> dict:
    """Look up an order by order number. Returns order plus line items.

    If ``for_customer_id`` is provided, the order is only returned when it
    belongs to that customer — otherwise we deny with ``found: False`` rather
    than disclosing that the order exists for someone else. This is the
    BOLA/IDOR defense: an authenticated customer cannot read another customer's
    order by guessing the order number.
    """
    order = db.scalar(select(Order).where(Order.order_number == order_number))
    if not order:
        return {"found": False, "order_number": order_number}
    if for_customer_id is not None and order.customer_id != for_customer_id:
        # Do not reveal that the order exists for a different customer.
        return {"found": False, "order_number": order_number, "not_owned": True}
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
    for_customer_id: int | None = None,
) -> dict:
    """Run the deterministic policy engine against the order.

    ``for_customer_id`` enforces the same BOLA/IDOR guard as ``get_order``:
    if provided and the order belongs to a different customer, the policy
    result is refused (order treated as not found). The agent therefore cannot
    be induced into running the policy engine — and the action tools gated on
    it — against another customer's order.
    """
    order = db.scalar(select(Order).where(Order.order_number == order_number))
    if not order:
        return {"error": "Order not found", "order_number": order_number}
    if for_customer_id is not None and order.customer_id != for_customer_id:
        return {"error": "Order not found", "order_number": order_number, "not_owned": True}

    cust = db.scalar(select(Customer).where(Customer.id == order.customer_id))
    refund_count = cust.refund_count_90d if cust else 0

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

    result = decision.to_dict()
    result["order_number"] = order_number
    return result


def process_refund(
    db: Session,
    order_number: str,
    *,
    refund_cents: int = 0,
    reason: str = "unwanted",
    for_customer_id: int | None = None,
) -> dict:
    """Prepare an approved refund action.

    Phase 5 will persist this as an append-only DB event. In Phase 4 this stays
    side-effect-free so the agent loop can be tested safely.
    """
    order = db.scalar(select(Order).where(Order.order_number == order_number))
    if not order:
        return {"processed": False, "error": "Order not found", "order_number": order_number}
    if for_customer_id is not None and order.customer_id != for_customer_id:
        return {"processed": False, "error": "Order not found", "order_number": order_number, "not_owned": True}
    return {
        "processed": True,
        "order_number": order_number,
        "refund_cents": refund_cents,
        "refund_dollars": round(refund_cents / 100, 2),
        "reason": reason,
        "action": "refund_ready",
    }


def deny_refund(
    db: Session,
    order_number: str,
    *,
    reason: str = "unwanted",
    for_customer_id: int | None = None,
) -> dict:
    """Prepare a denial action after the policy engine has denied the case."""
    order = db.scalar(select(Order).where(Order.order_number == order_number))
    if not order:
        return {"denied": False, "error": "Order not found", "order_number": order_number}
    if for_customer_id is not None and order.customer_id != for_customer_id:
        return {"denied": False, "error": "Order not found", "order_number": order_number, "not_owned": True}
    return {
        "denied": True,
        "order_number": order_number,
        "reason": reason,
        "action": "denial_ready",
    }


def flag_for_escalation(
    db: Session,
    order_number: str,
    *,
    reason: str = "unwanted",
    message: str = "",
    for_customer_id: int | None = None,
) -> dict:
    """Prepare a manual-review escalation after a policy hold verdict."""
    order = db.scalar(select(Order).where(Order.order_number == order_number))
    if not order:
        return {"flagged": False, "error": "Order not found", "order_number": order_number}
    if for_customer_id is not None and order.customer_id != for_customer_id:
        return {"flagged": False, "error": "Order not found", "order_number": order_number, "not_owned": True}
    return {
        "flagged": True,
        "order_number": order_number,
        "reason": reason,
        "message": message,
        "action": "manual_review_ready",
    }


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_customer",
            "description": "Look up a customer profile by email address.",
            "parameters": {
                "type": "object",
                "properties": {
                    "email": {"type": "string", "description": "Customer email address"},
                    "customer_name": {
                        "type": "string",
                        "description": "Optional customer name from the request; validation only.",
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
            "description": "Look up an order by order number, e.g. WP-1001.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_number": {"type": "string", "description": "Order number, e.g. WP-1001"},
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
                "Run the deterministic refund policy engine. This is the final "
                "authority for approve, deny, partial, store-credit, and manual-review verdicts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_number": {"type": "string"},
                    "reason": {
                        "type": "string",
                        "enum": sorted(REFUND_REASONS),
                    },
                    "wants_payment_method_change": {"type": "boolean"},
                    "is_bundle_partial": {"type": "boolean"},
                },
                "required": ["order_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "process_refund",
            "description": (
                "Prepare an approved refund action. This is allowed only after "
                "check_refund_policy returns an approving verdict in this same trace."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_number": {"type": "string"},
                    "refund_cents": {"type": "integer"},
                    "reason": {"type": "string", "enum": sorted(REFUND_REASONS)},
                },
                "required": ["order_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deny_refund",
            "description": (
                "Prepare a denial action. This is allowed only after "
                "check_refund_policy returns a denied verdict in this same trace."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_number": {"type": "string"},
                    "reason": {"type": "string", "enum": sorted(REFUND_REASONS)},
                },
                "required": ["order_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "flag_for_escalation",
            "description": (
                "Prepare a manual-review escalation. This is allowed only after "
                "check_refund_policy returns manual_review in this same trace."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_number": {"type": "string"},
                    "reason": {"type": "string", "enum": sorted(REFUND_REASONS)},
                    "message": {"type": "string"},
                },
                "required": ["order_number"],
            },
        },
    },
]


TOOL_FUNCTIONS = {
    "get_customer": get_customer,
    "get_order": get_order,
    "check_refund_policy": check_refund_policy,
    "process_refund": process_refund,
    "deny_refund": deny_refund,
    "flag_for_escalation": flag_for_escalation,
}
