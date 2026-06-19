"""Refund policy constants — the single source of truth for all clauses.

These mirror ``app/data/refund_policy.md`` exactly. The engine (Phase 3)
imports them by name; tests assert against them. Keeping the numeric thresholds
in one module means the policy doc, the engine, and the tests can never drift.
"""

from __future__ import annotations

# --- Time windows (calendar days) ---
STANDARD_RETURN_WINDOW_DAYS = 30
PRICE_ADJUSTMENT_WINDOW_DAYS = 7

# --- Abuse thresholds (refunds in trailing 90 days) ---
ABUSE_REVIEW_THRESHOLD = 3      # > 3 → manual_review
ABUSE_DENY_THRESHOLD = 5        # > 5 → denied
ABUSE_WINDOW_DAYS = 90

# --- Money (fractions of the item subtotal) ---
RESTOCKING_FEE_FRACTION = 0.15          # R6
RESTOCKING_FEE_MIN_ITEM_CENTS = 200_00  # R6: only items over $200
MISSING_PACKAGING_REFUND_FRACTION = 0.85  # R5: 85% if packaging missing

# --- Non-refundable item predicates (R3) ---
# A category predicate list: (attribute on OrderItem) -> deny
NON_REFUNDABLE_FLAGS: tuple[str, ...] = (
    "is_final_sale",
    "is_perishable",
    "is_personalized",
    "is_intimate",
    "is_gift_card",
)

# Categories that trigger the restocking fee when over the threshold.
RESTOCKING_CATEGORIES = ("electronics", "furniture")


class Clause:
    """Stable clause IDs for citations in decisions and the UI."""

    R1_WINDOW = "R1"
    R2_CONDITION = "R2"
    R3_NON_REFUNDABLE = "R3"
    R4_PAYMENT_METHOD = "R4"
    R5_PARTIAL_PACKAGING = "R5"
    R6_RESTOCKING = "R6"
    R7_SHIPPING = "R7"
    R8_DEFECTIVE = "R8"
    R9_GIFT = "R9"
    R10_ABUSE = "R10"
    R11_ORDER_STATUS = "R11"
    R12_PRICE_ADJUSTMENT = "R12"
    R13_BUNDLE = "R13"


# Human-readable label per clause, for the admin dashboard + agent citations.
CLAUSE_LABELS: dict[str, str] = {
    Clause.R1_WINDOW: "30-day return window",
    Clause.R2_CONDITION: "Item condition (unused, original packaging)",
    Clause.R3_NON_REFUNDABLE: "Non-refundable category",
    Clause.R4_PAYMENT_METHOD: "Original payment method only",
    Clause.R5_PARTIAL_PACKAGING: "Partial refund for missing packaging",
    Clause.R6_RESTOCKING: "Restocking fee (electronics/furniture > $200)",
    Clause.R7_SHIPPING: "Shipping non-refundable",
    Clause.R8_DEFECTIVE: "Defective / incorrect item",
    Clause.R9_GIFT: "Gift returns = store credit",
    Clause.R10_ABUSE: "Refund abuse threshold",
    Clause.R11_ORDER_STATUS: "Order must be paid",
    Clause.R12_PRICE_ADJUSTMENT: "Price-adjustment window (7 days)",
    Clause.R13_BUNDLE: "Bundles returned whole",
}
