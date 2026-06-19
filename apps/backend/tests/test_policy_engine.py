"""Tests for the deterministic refund policy engine.

Every clause R1–R13 is tested with a concrete scenario. Tests read from the
seeded DB (conftest.py provides `db_session`) so they exercise real ORM
objects end-to-end through the engine. Pure-func tests for edge arithmetic live
at the bottom.

Run:  pytest tests/test_policy_engine.py -v
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select

from app.models import Customer, Order, RefundReason, RefundVerdict
from app.policy.engine import evaluate
from app.policy.rules import Clause

# Anchor "now" to match the seed data (TODAY = 2026-06-19).
NOW = datetime(2026, 6, 19, 12, 0, 0)


# -----------------------------------------------------------------------
# Helper: load an order by number from the seeded session
# -----------------------------------------------------------------------


def _load(db, order_number: str):
    """Return (customer, order, items) from seeded data."""
    order = db.scalar(select(Order).where(Order.order_number == order_number))
    assert order is not None, f"Order {order_number} not found in seed data"
    cust = db.scalar(select(Customer).where(Customer.id == order.customer_id))
    return cust, order, order.items


# -----------------------------------------------------------------------
# R1 — standard 30-day window
# -----------------------------------------------------------------------


class TestR1Window:
    def test_within_window_approved(self, db_session):
        _cust, order, _items = _load(db_session, "WP-1001")
        # delivered 12 days ago → within 30
        d = evaluate(order, reason=RefundReason.unwanted, refund_count_90d=0, now=NOW)
        assert d.verdict == RefundVerdict.approved
        assert d.refund_cents == 12900  # item only; shipping non-refundable (R7)

    def test_expired_denied(self, db_session):
        _cust, order, _items = _load(db_session, "WP-1002")
        # delivered 45 days ago → outside 30
        d = evaluate(order, reason=RefundReason.unwanted, refund_count_90d=0, now=NOW)
        assert d.verdict == RefundVerdict.denied
        assert Clause.R1_WINDOW in d.clauses_hit


# -----------------------------------------------------------------------
# R2 — item condition
# -----------------------------------------------------------------------


class TestR2Condition:
    def test_used_item_denied(self, db_session):
        _cust, order, _items = _load(db_session, "WP-1019")
        # reported_unused=False, is_defective=False
        d = evaluate(order, reason=RefundReason.unwanted, refund_count_90d=0, now=NOW)
        assert d.verdict == RefundVerdict.denied
        assert Clause.R2_CONDITION in d.clauses_hit

    def test_defective_used_approved(self, db_session):
        _cust, order, _items = _load(db_session, "WP-1019")
        # Override to defective → R8 takes priority over R2
        for item in order.items:
            item.is_defective = True
        d = evaluate(order, reason=RefundReason.defective, refund_count_90d=0, now=NOW)
        assert d.verdict == RefundVerdict.approved
        assert Clause.R8_DEFECTIVE in d.clauses_hit


# -----------------------------------------------------------------------
# R3 — non-refundable categories
# -----------------------------------------------------------------------


class TestR3NonRefundable:
    @pytest.mark.parametrize("order_num", ["WP-1003", "WP-1004", "WP-1005", "WP-1006"])
    def test_final_sale_perishable_personalized_intimate_denied(self, db_session, order_num):
        _cust, order, _items = _load(db_session, order_num)
        d = evaluate(order, reason=RefundReason.unwanted, refund_count_90d=0, now=NOW)
        assert d.verdict == RefundVerdict.denied
        assert Clause.R3_NON_REFUNDABLE in d.clauses_hit

    def test_digital_accessed_denied(self, db_session):
        _cust, order, _items = _load(db_session, "WP-1007")
        d = evaluate(order, reason=RefundReason.unwanted, refund_count_90d=0, now=NOW)
        assert d.verdict == RefundVerdict.denied
        assert Clause.R3_NON_REFUNDABLE in d.clauses_hit

    def test_digital_not_accessed_approved(self, db_session):
        _cust, order, _items = _load(db_session, "WP-1008")
        d = evaluate(order, reason=RefundReason.unwanted, refund_count_90d=0, now=NOW)
        assert d.verdict == RefundVerdict.approved


# -----------------------------------------------------------------------
# R4 — original payment method (tested via pure func below)
# -----------------------------------------------------------------------


class TestR4PaymentMethod:
    def test_payment_redirect_denied(self, db_session):
        _cust, order, _items = _load(db_session, "WP-1001")
        d = evaluate(
            order,
            reason=RefundReason.unwanted,
            refund_count_90d=0,
            wants_payment_method_change=True,
            now=NOW,
        )
        assert d.verdict == RefundVerdict.denied
        assert Clause.R4_PAYMENT_METHOD in d.clauses_hit


# -----------------------------------------------------------------------
# R5 — partial refund for missing packaging
# -----------------------------------------------------------------------


class TestR5PartialPackaging:
    def test_missing_packaging_partial(self, db_session):
        _cust, order, _items = _load(db_session, "WP-1009")
        d = evaluate(order, reason=RefundReason.unwanted, refund_count_90d=0, now=NOW)
        assert d.verdict == RefundVerdict.approved_partial
        assert d.refund_cents == 5950  # 7000 * 0.85
        assert Clause.R5_PARTIAL_PACKAGING in d.clauses_hit


# -----------------------------------------------------------------------
# R6 — restocking fee on electronics/furniture > $200
# -----------------------------------------------------------------------


class TestR6Restocking:
    def test_electronics_over_200_restocking(self, db_session):
        _cust, order, _items = _load(db_session, "WP-1010")
        d = evaluate(order, reason=RefundReason.unwanted, refund_count_90d=0, now=NOW)
        assert d.verdict == RefundVerdict.approved_partial
        # $350 item - 15% = $297.50 → 29750 cents
        assert d.refund_cents == 29750
        assert Clause.R6_RESTOCKING in d.clauses_hit

    def test_furniture_over_200_restocking(self, db_session):
        # Build an ad-hoc furniture order > $200
        _cust, order, _items = _load(db_session, "WP-1016")
        # Change pending→paid, set furniture category
        from app.models import OrderStatus, ItemCategory
        order.status = OrderStatus.paid
        order.delivery_date = NOW  # just delivered
        for item in order.items:
            item.category = ItemCategory.furniture
            item.price_cents = 25000
        order.subtotal_cents = 25000
        d = evaluate(order, reason=RefundReason.unwanted, refund_count_90d=0, now=NOW)
        assert d.verdict == RefundVerdict.approved_partial
        assert Clause.R6_RESTOCKING in d.clauses_hit
        assert d.refund_cents == 21250  # 25000 - 3750


# -----------------------------------------------------------------------
# R7 — shipping non-refundable
# -----------------------------------------------------------------------


class TestR7Shipping:
    def test_shipping_not_included_in_normal_refund(self, db_session):
        _cust, order, _items = _load(db_session, "WP-1011")
        d = evaluate(order, reason=RefundReason.unwanted, refund_count_90d=0, now=NOW)
        assert d.verdict == RefundVerdict.approved
        assert d.refund_cents == 6000  # subtotal only, not 7200 (shipping excluded)
        assert Clause.R7_SHIPPING in d.clauses_hit


# -----------------------------------------------------------------------
# R8 — defective / incorrect → full refund, no restocking, shipping included
# -----------------------------------------------------------------------


class TestR8Defective:
    def test_defective_full_refund_includes_shipping(self, db_session):
        _cust, order, _items = _load(db_session, "WP-1012")
        d = evaluate(order, reason=RefundReason.defective, refund_count_90d=0, now=NOW)
        assert d.verdict == RefundVerdict.approved
        assert d.refund_cents == 18800  # subtotal 18000 + shipping 800
        assert Clause.R8_DEFECTIVE in d.clauses_hit
        assert Clause.R6_RESTOCKING not in d.clauses_hit  # no restocking

    def test_defective_bypasses_window(self, db_session):
        # WP-1002 is 45 days old but if we mark it defective, R1 is bypassed
        _cust, order, _items = _load(db_session, "WP-1002")
        for item in order.items:
            item.is_defective = True
        d = evaluate(order, reason=RefundReason.defective, refund_count_90d=0, now=NOW)
        assert d.verdict == RefundVerdict.approved
        assert Clause.R1_WINDOW not in d.clauses_hit
        assert Clause.R8_DEFECTIVE in d.clauses_hit


# -----------------------------------------------------------------------
# R9 — gift returns = store credit
# -----------------------------------------------------------------------


class TestR9Gift:
    def test_gift_store_credit(self, db_session):
        _cust, order, _items = _load(db_session, "WP-1013")
        d = evaluate(order, reason=RefundReason.unwanted, refund_count_90d=0, now=NOW)
        assert d.verdict == RefundVerdict.approved_store_credit
        assert d.refund_cents == 9500
        assert Clause.R9_GIFT in d.clauses_hit


# -----------------------------------------------------------------------
# R10 — refund abuse thresholds
# -----------------------------------------------------------------------


class TestR10Abuse:
    def test_4_refunds_manual_review(self, db_session):
        _cust, order, _items = _load(db_session, "WP-1014")
        # Customer has refund_count_90d=4
        d = evaluate(order, reason=RefundReason.unwanted, refund_count_90d=4, now=NOW)
        assert d.verdict == RefundVerdict.manual_review
        assert Clause.R10_ABUSE in d.clauses_hit

    def test_6_refunds_denied(self, db_session):
        _cust, order, _items = _load(db_session, "WP-1015")
        d = evaluate(order, reason=RefundReason.unwanted, refund_count_90d=6, now=NOW)
        assert d.verdict == RefundVerdict.denied
        assert Clause.R10_ABUSE in d.clauses_hit


# -----------------------------------------------------------------------
# R11 — order status must be 'paid'
# -----------------------------------------------------------------------


class TestR11OrderStatus:
    def test_pending_denied(self, db_session):
        _cust, order, _items = _load(db_session, "WP-1016")
        d = evaluate(order, reason=RefundReason.unwanted, refund_count_90d=0, now=NOW)
        assert d.verdict == RefundVerdict.denied
        assert Clause.R11_ORDER_STATUS in d.clauses_hit


# -----------------------------------------------------------------------
# R12 — price adjustment within 7 days
# -----------------------------------------------------------------------


class TestR12PriceAdjustment:
    def test_within_7_days_approved(self, db_session):
        _cust, order, _items = _load(db_session, "WP-1017")
        # purchased 5 days ago → within 7
        d = evaluate(order, reason=RefundReason.price_adjustment, refund_count_90d=0, now=NOW)
        assert d.verdict == RefundVerdict.approved
        assert Clause.R12_PRICE_ADJUSTMENT in d.clauses_hit

    def test_past_7_days_denied(self, db_session):
        _cust, order, _items = _load(db_session, "WP-1001")
        # purchased 14 days ago → outside 7
        d = evaluate(order, reason=RefundReason.price_adjustment, refund_count_90d=0, now=NOW)
        assert d.verdict == RefundVerdict.denied
        assert Clause.R12_PRICE_ADJUSTMENT in d.clauses_hit


# -----------------------------------------------------------------------
# R13 — bundles returned whole
# -----------------------------------------------------------------------


class TestR13Bundle:
    def test_bundle_partial_denied(self, db_session):
        _cust, order, _items = _load(db_session, "WP-1018")
        d = evaluate(
            order,
            reason=RefundReason.unwanted,
            refund_count_90d=0,
            is_bundle_partial=True,
            now=NOW,
        )
        assert d.verdict == RefundVerdict.denied
        assert Clause.R13_BUNDLE in d.clauses_hit

    def test_bundle_whole_approved(self, db_session):
        _cust, order, _items = _load(db_session, "WP-1018")
        d = evaluate(
            order,
            reason=RefundReason.unwanted,
            refund_count_90d=0,
            is_bundle_partial=False,
            now=NOW,
        )
        assert d.verdict == RefundVerdict.approved


# -----------------------------------------------------------------------
# Pure-function edge cases (no DB needed)
# -----------------------------------------------------------------------


class TestEdgeCases:
    """Arithmetic and boundary checks that don't need seed data."""

    def _make_order(self, **overrides):
        """Minimal Order-like object for pure tests."""
        from app.models import OrderStatus, ItemCategory

        class FakeItem:
            def __init__(self, **kw):
                for k, v in kw.items():
                    setattr(self, k, v)

        class FakeOrder:
            def __init__(self, **kw):
                self.status = OrderStatus.paid
                self.is_gift = False
                self.is_bundle = False
                self.subtotal_cents = 10000
                self.shipping_cents = 500
                self.total_cents = 10500
                self.delivery_date = NOW
                self.purchase_date = NOW
                self.items = []
                for k, v in kw.items():
                    setattr(self, k, v)

        order = FakeOrder()
        order.items = [FakeItem(
            sku="T", name="Test Item", category=ItemCategory.apparel,
            price_cents=10000, quantity=1,
            is_final_sale=False, is_perishable=False, is_personalized=False,
            is_intimate=False, is_digital=False, is_gift_card=False,
            digital_accessed=False, reported_unused=True,
            has_original_packaging=True, is_defective=False,
        )]
        for k, v in overrides.items():
            setattr(order, k, v)
        return order

    def test_zero_refund_stays_nonnegative(self):
        order = self._make_order()
        order.subtotal_cents = 0
        d = evaluate(order, now=NOW)
        assert d.refund_cents == 0

    def test_refund_cents_never_negative(self):
        order = self._make_order()
        # Simulate a tiny item with restocking
        from app.models import ItemCategory
        order.items[0].category = ItemCategory.electronics
        order.items[0].price_cents = 20100  # $201.00
        order.subtotal_cents = 20100
        order.items[0].has_original_packaging = False  # triggers R5 + R6 stacking
        d = evaluate(order, now=NOW)
        assert d.refund_cents >= 0

    def test_combined_deductions_stacked_correctly(self):
        """R5 partial + R6 restocking should both apply."""
        order = self._make_order()
        from app.models import ItemCategory
        order.items[0].category = ItemCategory.electronics
        order.items[0].price_cents = 30000  # $300
        order.subtotal_cents = 30000
        order.items[0].has_original_packaging = False
        d = evaluate(order, now=NOW)
        # R5: 30000 * 0.85 = 25500, then R6: 25500 - 4500 (15% of 30000) = 21000
        assert Clause.R5_PARTIAL_PACKAGING in d.clauses_hit
        assert Clause.R6_RESTOCKING in d.clauses_hit
        assert d.refund_cents == 21000

    def test_gift_plus_restocking_is_store_credit_partial(self):
        """R9 + R6 → store credit with partial amount."""
        order = self._make_order(is_gift=True)
        from app.models import ItemCategory
        order.items[0].category = ItemCategory.electronics
        order.items[0].price_cents = 30000
        order.subtotal_cents = 30000
        d = evaluate(order, now=NOW)
        assert d.verdict == RefundVerdict.approved_store_credit
        assert Clause.R9_GIFT in d.clauses_hit
        assert Clause.R6_RESTOCKING in d.clauses_hit
