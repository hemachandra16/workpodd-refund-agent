"""Deterministic refund policy engine.

This is the security-critical core of the entire system: it takes an Order and
a requested refund reason, and returns a verdict that is **final**. The LLM
agent is structurally incapable of overriding it — it can only phrase whatever
verdict the engine produces. Prompt-injecting the model cannot approve a refund
that violates a clause here.

The engine is pure (no I/O, no LLM, no clock injection beyond the ``now``
argument) so it is trivially unit-testable and deterministic in CI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.models import (
    ItemCategory,
    Order,
    OrderItem,
    OrderStatus,
    RefundReason,
    RefundVerdict,
)
from app.policy.rules import (
    ABUSE_DENY_THRESHOLD,
    ABUSE_REVIEW_THRESHOLD,
    ABUSE_WINDOW_DAYS,
    CLAUSE_LABELS,
    MISSING_PACKAGING_REFUND_FRACTION,
    NON_REFUNDABLE_FLAGS,
    PRICE_ADJUSTMENT_WINDOW_DAYS,
    RESTOCKING_CATEGORIES,
    RESTOCKING_FEE_FRACTION,
    RESTOCKING_FEE_MIN_ITEM_CENTS,
    STANDARD_RETURN_WINDOW_DAYS,
    Clause,
)


@dataclass
class RefundDecision:
    """The complete, machine-trustworthy result of a policy evaluation."""

    verdict: RefundVerdict
    refund_cents: int = 0
    clauses_hit: list[str] = field(default_factory=list)
    rationale: str = ""
    # Breakdown for transparency in the admin UI / agent citation.
    breakdown: dict[str, int] = field(default_factory=dict)

    @property
    def clause_labels(self) -> list[str]:
        return [f"{c} — {CLAUSE_LABELS[c]}" for c in self.clauses_hit if c in CLAUSE_LABELS]

    def to_dict(self) -> dict[str, object]:
        return {
            "verdict": self.verdict.value,
            "refund_cents": self.refund_cents,
            "refund_dollars": round(self.refund_cents / 100, 2),
            "clauses_hit": self.clauses_hit,
            "clause_labels": self.clause_labels,
            "rationale": self.rationale,
            "breakdown": self.breakdown,
        }


def _days_since(later_than: datetime, now: datetime) -> int:
    """Whole calendar days between two datetimes (never negative)."""
    delta = now - later_than
    return max(0, delta.days)


def evaluate(
    order: Order,
    *,
    reason: RefundReason = RefundReason.unwanted,
    refund_count_90d: int = 0,
    wants_payment_method_change: bool = False,
    is_bundle_partial: bool = False,
    now: Optional[datetime] = None,
) -> RefundDecision:
    """Evaluate a refund request against every applicable clause.

    Order of checks matters: the most decisive, cheap-to-compute hard denials
    run first. Once we reach a deny, we short-circuit. Approvals accumulate
    deductions (restocking, shipping, partial) rather than short-circuiting.
    """
    now = now or datetime.now()
    decision = RefundDecision(verdict=RefundVerdict.approved)
    clauses: list[str] = []
    notes: list[str] = []

    # ----- R11: order status must be 'paid' (hard deny) -----
    if order.status != OrderStatus.paid:
        clauses.append(Clause.R11_ORDER_STATUS)
        return RefundDecision(
            verdict=RefundVerdict.denied,
            clauses_hit=clauses,
            rationale=f"Order status is '{order.status.value}'; only 'paid' orders are refundable.",
        )

    # ----- R10: abuse (hard deny / hold) -----
    if refund_count_90d > ABUSE_DENY_THRESHOLD:
        clauses.append(Clause.R10_ABUSE)
        return RefundDecision(
            verdict=RefundVerdict.denied,
            clauses_hit=clauses,
            rationale=(
                f"Refund denied: {refund_count_90d} refunds in the last "
                f"{ABUSE_WINDOW_DAYS} days exceeds the abuse limit of "
                f"{ABUSE_DENY_THRESHOLD}."
            ),
        )
    if refund_count_90d > ABUSE_REVIEW_THRESHOLD:
        clauses.append(Clause.R10_ABUSE)
        return RefundDecision(
            verdict=RefundVerdict.manual_review,
            clauses_hit=clauses,
            rationale=(
                f"Manual review required: {refund_count_90d} refunds in the last "
                f"{ABUSE_WINDOW_DAYS} days triggers review (>{ABUSE_REVIEW_THRESHOLD})."
            ),
        )

    # ----- R4: must refund to original payment method (hard deny on redirect) -----
    if wants_payment_method_change:
        clauses.append(Clause.R4_PAYMENT_METHOD)
        return RefundDecision(
            verdict=RefundVerdict.denied,
            clauses_hit=clauses,
            rationale="Refund denied: refunds are issued to the original payment method only.",
        )

    # ----- R12: price adjustment window (only reason that uses this clause) -----
    if reason == RefundReason.price_adjustment:
        days = _days_since(order.purchase_date, now)
        if days > PRICE_ADJUSTMENT_WINDOW_DAYS:
            clauses.append(Clause.R12_PRICE_ADJUSTMENT)
            return RefundDecision(
                verdict=RefundVerdict.denied,
                clauses_hit=clauses,
                rationale=(
                    f"Price-adjustment denied: {days} days since purchase exceeds the "
                    f"{PRICE_ADJUSTMENT_WINDOW_DAYS}-day window."
                ),
            )
        # Within window → approved price difference (mock: full subtotal as the diff).
        clauses.append(Clause.R12_PRICE_ADJUSTMENT)
        return RefundDecision(
            verdict=RefundVerdict.approved,
            refund_cents=order.subtotal_cents,
            clauses_hit=clauses,
            rationale="Price-adjustment approved within the 7-day window.",
            breakdown={"price_difference": order.subtotal_cents},
        )

    # ----- R1: standard window (only defective items exempt) -----
    is_defective_claim = reason in {
        RefundReason.defective,
        RefundReason.damaged_shipping,
        RefundReason.wrong_item,
        RefundReason.not_as_described,
    }
    if order.delivery_date is not None:
        days_since_delivery = _days_since(order.delivery_date, now)
        if days_since_delivery > STANDARD_RETURN_WINDOW_DAYS and not is_defective_claim:
            clauses.append(Clause.R1_WINDOW)
            return RefundDecision(
                verdict=RefundVerdict.denied,
                clauses_hit=clauses,
                rationale=(
                    f"Refund denied: {days_since_delivery} days since delivery exceeds the "
                    f"{STANDARD_RETURN_WINDOW_DAYS}-day return window."
                ),
            )

    # ----- R13: bundles must be returned whole (hard deny on partial) -----
    if order.is_bundle and is_bundle_partial:
        clauses.append(Clause.R13_BUNDLE)
        return RefundDecision(
            verdict=RefundVerdict.denied,
            clauses_hit=clauses,
            rationale="Refund denied: bundle items must be returned as a complete bundle.",
        )

    # ----- R3: per-item non-refundable checks -----
    # (digital-once-accessed is handled below with the rest of the amount math.)
    for item in order.items:
        flag_hit = next((f for f in NON_REFUNDABLE_FLAGS if getattr(item, f)), None)
        if flag_hit:
            label = flag_hit.replace("is_", "").replace("_", " ")
            clauses.append(Clause.R3_NON_REFUNDABLE)
            return RefundDecision(
                verdict=RefundVerdict.denied,
                clauses_hit=clauses,
                rationale=f"Refund denied: '{item.name}' is non-refundable ({label}).",
            )
        # Digital accessed → non-refundable (R3 carve-out: pre-access is refundable).
        if item.is_digital and item.digital_accessed:
            clauses.append(Clause.R3_NON_REFUNDABLE)
            return RefundDecision(
                verdict=RefundVerdict.denied,
                clauses_hit=clauses,
                rationale=f"Refund denied: '{item.name}' is a digital product that has been accessed.",
            )

    # ----- R2: item condition (used + not defective → deny) -----
    for item in order.items:
        if not item.reported_unused and not item.is_defective:
            clauses.append(Clause.R2_CONDITION)
            return RefundDecision(
                verdict=RefundVerdict.denied,
                clauses_hit=clauses,
                rationale=f"Refund denied: '{item.name}' was used and is not defective.",
            )

    # ----- R8: defective path → full refund, no restocking, shipping refunded -----
    any_defective = any(item.is_defective for item in order.items) or is_defective_claim
    if any_defective:
        clauses.append(Clause.R8_DEFECTIVE)
        refund = order.subtotal_cents + order.shipping_cents
        return RefundDecision(
            verdict=RefundVerdict.approved,
            refund_cents=refund,
            clauses_hit=clauses,
            rationale="Full refund approved: item defective/incorrect. No restocking fee; shipping refunded.",
            breakdown={"items": order.subtotal_cents, "shipping": order.shipping_cents},
        )

    # ----- From here: a normal, eligible return. Compute deductions. -----
    refund = order.subtotal_cents
    breakdown: dict[str, int] = {"items": order.subtotal_cents}

    # ----- R5: missing packaging → partial (85%) -----
    missing_packaging = any(not item.has_original_packaging for item in order.items)
    if missing_packaging:
        clauses.append(Clause.R5_PARTIAL_PACKAGING)
        refund = round(refund * MISSING_PACKAGING_REFUND_FRACTION)
        breakdown["packaging_deduction"] = order.subtotal_cents - refund
        notes.append("Partial refund (85%) applied for missing packaging.")

    # ----- R6: restocking fee on electronics/furniture > $200 -----
    restocking = 0
    for item in order.items:
        if (
            item.category.value in RESTOCKING_CATEGORIES
            and item.price_cents > RESTOCKING_FEE_MIN_ITEM_CENTS
        ):
            clauses.append(Clause.R6_RESTOCKING)
            fee = round(item.price_cents * RESTOCKING_FEE_FRACTION)
            restocking += fee
    if restocking:
        refund -= restocking
        breakdown["restocking_fee"] = restocking
        notes.append(f"Restocking fee of ${restocking / 100:.2f} applied.")

    # ----- R7: shipping non-refundable for normal returns -----
    if order.shipping_cents:
        clauses.append(Clause.R7_SHIPPING)
        breakdown["shipping_non_refundable"] = order.shipping_cents
        notes.append("Original shipping is non-refundable.")

    # ----- R9: gift returns → store credit only -----
    final_verdict = RefundVerdict.approved
    if order.is_gift:
        clauses.append(Clause.R9_GIFT)
        final_verdict = RefundVerdict.approved_store_credit
        notes.append("Issued as store credit (gift return).")

    if missing_packaging or restocking:
        final_verdict = (
            RefundVerdict.approved_store_credit
            if order.is_gift
            else RefundVerdict.approved_partial
        )

    rationale = "Refund approved."
    if notes:
        rationale += " " + " ".join(notes)
    rationale += f" Final refund: ${refund / 100:.2f}."

    return RefundDecision(
        verdict=final_verdict,
        refund_cents=max(0, refund),
        clauses_hit=clauses,
        rationale=rationale,
        breakdown=breakdown,
    )


# Convenience for tools that hold raw category strings.
def category_is_restockable(category: ItemCategory | str) -> bool:
    return (category.value if isinstance(category, ItemCategory) else category) in RESTOCKING_CATEGORIES
