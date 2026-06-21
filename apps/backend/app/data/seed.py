"""Mock CRM data — 15 customer profiles, each exercising a policy clause.

Every profile is tagged with the clause(s) it demonstrates so the Loom demo
and the unit tests have deterministic, named scenarios. This is mock data:
names/emails are fictional, payment instruments are stored as last-4 only.

Usage:
    python -m app.data.seed            # create + populate the SQLite DB
    python -m app.data.seed --reset    # drop + recreate (dev only)

The seeder is idempotent on order_number/email and safe to re-run.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Base, SessionLocal
from app.models import (
    Customer,
    ItemCategory,
    Order,
    OrderItem,
    OrderStatus,
)

settings = get_settings()

# "Today" for seeding purposes — anchored so delivery windows are deterministic.
TODAY = datetime(2026, 6, 19, 12, 0, 0)
D = lambda days_ago: TODAY - timedelta(days=days_ago)  # noqa: E731


def _item(**kw: Any) -> dict[str, Any]:
    """Item factory with sane defaults so each case stays readable."""
    base = {
        "sku": "SKU-0000",
        "name": "Item",
        "category": ItemCategory.apparel,
        "price_cents": 5000,
        "quantity": 1,
        "is_final_sale": False,
        "is_perishable": False,
        "is_personalized": False,
        "is_intimate": False,
        "is_digital": False,
        "is_gift_card": False,
        "digital_accessed": False,
        "reported_unused": True,
        "has_original_packaging": True,
        "is_defective": False,
    }
    base.update(kw)
    return base


def _order(**kw: Any) -> dict[str, Any]:
    base = {
        "order_number": "WP-0000",
        "status": OrderStatus.paid,
        "is_gift": False,
        "is_bundle": False,
        "subtotal_cents": 0,
        "shipping_cents": 500,
        "delivery_date": D(10),
        "purchase_date": D(12),
        "items": [],
    }
    base.update(kw)
    return base


# Each entry: (case_label, customer_dict, [order_dict, ...])
# Labels document which clause(s) the case triggers for the demo/tests.
CASES: list[tuple[str, dict[str, Any], list[dict[str, Any]]]] = [
    # ---- R1: within 30-day window → approved ----
    (
        "R1 standard approved",
        {"email": "amelia.silver@example.com", "name": "Amelia Silver", "token_last4": "4242"},
        [_order(
            order_number="WP-1001",
            subtotal_cents=12900, shipping_cents=500, total_cents=13400,
            delivery_date=D(12), purchase_date=D(14),
            items=[_item(sku="SKU-A1", name="Cotton Crew Sweater", price_cents=12900)],
        )],
    ),
    # ---- R1: outside 30-day window → denied ----
    (
        "R1 window expired denied",
        {"email": "bruno.hale@example.com", "name": "Bruno Hale", "token_last4": "1881"},
        [_order(
            order_number="WP-1002",
            subtotal_cents=8900, shipping_cents=500, total_cents=9400,
            delivery_date=D(45), purchase_date=D(47),
            items=[_item(sku="SKU-A2", name="Linen Shirt", price_cents=8900)],
        )],
    ),
    # ---- R3: final sale → denied ----
    (
        "R3 final sale denied",
        {"email": "chen.lupark@example.com", "name": "Chen Lupark", "token_last4": "9090"},
        [_order(
            order_number="WP-1003",
            subtotal_cents=4500, shipping_cents=500, total_cents=5000,
            delivery_date=D(5), purchase_date=D(7),
            items=[_item(sku="SKU-A3", name="Clearance Tee", price_cents=4500, is_final_sale=True)],
        )],
    ),
    # ---- R3: perishable → denied ----
    (
        "R3 perishable denied",
        {"email": "devi.narayan@example.com", "name": "Devi Narayan", "token_last4": "3321"},
        [_order(
            order_number="WP-1004",
            subtotal_cents=3200, shipping_cents=500, total_cents=3700,
            delivery_date=D(3), purchase_date=D(5),
            items=[_item(sku="SKU-G1", name="Gourmet Coffee Beans", category=ItemCategory.grocery,
                         price_cents=3200, is_perishable=True)],
        )],
    ),
    # ---- R3: personalized → denied ----
    (
        "R3 personalized denied",
        {"email": "elias.wren@example.com", "name": "Elias Wren", "token_last4": "7765"},
        [_order(
            order_number="WP-1005",
            subtotal_cents=12000, shipping_cents=0, total_cents=12000,
            delivery_date=D(8), purchase_date=D(10),
            items=[_item(sku="SKU-J1", name="Engraved Bracelet", category=ItemCategory.jewelry,
                         price_cents=12000, is_personalized=True)],
        )],
    ),
    # ---- R3: intimate apparel → denied ----
    (
        "R3 intimate denied",
        {"email": "fatima.zar@example.com", "name": "Fatima Zar", "token_last4": "1188"},
        [_order(
            order_number="WP-1006",
            subtotal_cents=3800, shipping_cents=500, total_cents=4300,
            delivery_date=D(6), purchase_date=D(8),
            items=[_item(sku="SKU-A4", name="Swimwear One-Piece", price_cents=3800, is_intimate=True)],
        )],
    ),
    # ---- R3: digital once accessed → denied ----
    (
        "R3 digital accessed denied",
        {"email": "georg.orwell@example.com", "name": "Georg Orwell", "token_last4": "2025"},
        [_order(
            order_number="WP-1007", subtotal_cents=1999, shipping_cents=0, total_cents=1999,
            delivery_date=D(2), purchase_date=D(3),
            items=[_item(sku="SKU-D1", name="E-Book: Recipes", category=ItemCategory.digital,
                         price_cents=1999, is_digital=True, digital_accessed=True)],
        )],
    ),
    # ---- R3 edge: digital NOT accessed → approved (refunds allowed pre-access) ----
    (
        "R3 digital not-accessed approved",
        {"email": "harriet.tubman@example.com", "name": "Harriet Tubman", "token_last4": "6633"},
        [_order(
            order_number="WP-1008", subtotal_cents=4999, shipping_cents=0, total_cents=4999,
            delivery_date=D(1), purchase_date=D(2),
            items=[_item(sku="SKU-D2", name="Software License", category=ItemCategory.digital,
                         price_cents=4999, is_digital=True, digital_accessed=False)],
        )],
    ),
    # ---- R5: missing packaging → approved_partial (85%) ----
    (
        "R5 missing packaging partial",
        {"email": "ivy.chen@example.com", "name": "Ivy Chen", "token_last4": "9001"},
        [_order(
            order_number="WP-1009", subtotal_cents=7000, shipping_cents=500, total_cents=7500,
            delivery_date=D(15), purchase_date=D(17),
            items=[_item(sku="SKU-H1", name="Ceramic Vase", category=ItemCategory.home,
                         price_cents=7000, has_original_packaging=False)],
        )],
    ),
    # ---- R6: electronics > $200 → approved_partial with 15% restocking ----
    (
        "R6 restocking fee partial",
        {"email": "jacob.stone@example.com", "name": "Jacob Stone", "token_last4": "4545"},
        [_order(
            order_number="WP-1010", subtotal_cents=35000, shipping_cents=0, total_cents=35000,
            delivery_date=D(9), purchase_date=D(11),
            items=[_item(sku="SKU-E1", name="Wireless Headphones", category=ItemCategory.electronics,
                         price_cents=35000)],
        )],
    ),
    # ---- R7: standard return, shipping non-refundable → approved (item only) ----
    (
        "R7 shipping non-refundable approved",
        {"email": "keiko.mori@example.com", "name": "Keiko Mori", "token_last4": "7788"},
        [_order(
            order_number="WP-1011", subtotal_cents=6000, shipping_cents=1200, total_cents=7200,
            delivery_date=D(7), purchase_date=D(9),
            items=[_item(sku="SKU-S1", name="Running Shoes", category=ItemCategory.sports,
                         price_cents=6000)],
        )],
    ),
    # ---- R8: defective → full refund, no restocking, shipping refunded ----
    (
        "R8 defective full refund",
        {"email": "liam.foster@example.com", "name": "Liam Foster", "token_last4": "1212"},
        [_order(
            order_number="WP-1012", subtotal_cents=18000, shipping_cents=800, total_cents=18800,
            delivery_date=D(20), purchase_date=D(22),
            items=[_item(sku="SKU-E2", name="Blender (defective)", category=ItemCategory.electronics,
                         price_cents=18000, is_defective=True)],
        )],
    ),
    # ---- R9: gift return → store credit only ----
    (
        "R9 gift store credit",
        {"email": "maya.patel@example.com", "name": "Maya Patel", "token_last4": "5555"},
        [_order(
            order_number="WP-1013", subtotal_cents=9500, shipping_cents=500, total_cents=10000,
            delivery_date=D(11), purchase_date=D(13), is_gift=True,
            items=[_item(sku="SKU-B1", name="Skincare Set", category=ItemCategory.beauty,
                         price_cents=9500)],
        )],
    ),
    # ---- R10: abuse — 4 refunds in 90d → manual_review ----
    (
        "R10 abuse manual review",
        {"email": "noah.katz@example.com", "name": "Noah Katz", "token_last4": "3030",
         "refund_count_90d": 4},
        [_order(
            order_number="WP-1014", subtotal_cents=5400, shipping_cents=500, total_cents=5900,
            delivery_date=D(4), purchase_date=D(6),
            items=[_item(sku="SKU-H2", name="Desk Lamp", category=ItemCategory.home,
                         price_cents=5400)],
        )],
    ),
    # ---- R10: abuse — 6 refunds in 90d → denied ----
    (
        "R10 abuse denied",
        {"email": "olivia.rune@example.com", "name": "Olivia Rune", "token_last4": "4040",
         "refund_count_90d": 6},
        [_order(
            order_number="WP-1015", subtotal_cents=4200, shipping_cents=500, total_cents=4700,
            delivery_date=D(4), purchase_date=D(6),
            items=[_item(sku="SKU-H3", name="Throw Blanket", category=ItemCategory.home,
                         price_cents=4200)],
        )],
    ),
    # ---- R11: order not paid → denied ----
    (
        "R11 order not paid denied",
        {"email": "piotr.zarek@example.com", "name": "Piotr Zarek", "token_last4": "8899"},
        [_order(
            order_number="WP-1016", subtotal_cents=15000, shipping_cents=0, total_cents=15000,
            delivery_date=None, purchase_date=D(1), status=OrderStatus.pending,
            items=[_item(sku="SKU-F1", name="Office Chair", category=ItemCategory.furniture,
                         price_cents=15000)],
        )],
    ),
    # ---- R12: price adjustment within 7 days → approved (the difference) ----
    (
        "R12 price adjustment approved",
        {"email": "quinn.lee@example.com", "name": "Quinn Lee", "token_last4": "6161"},
        [_order(
            order_number="WP-1017", subtotal_cents=8000, shipping_cents=0, total_cents=8000,
            delivery_date=D(4), purchase_date=D(5),
            items=[_item(sku="SKU-A5", name="Wool Coat", price_cents=8000, is_defective=False)],
        )],
    ),
    # ---- R13: bundle partial return → denied ----
    (
        "R13 bundle partial denied",
        {"email": "rina.adebayo@example.com", "name": "Rina Adebayo", "token_last4": "2727"},
        [_order(
            order_number="WP-1018", subtotal_cents=22000, shipping_cents=0, total_cents=22000,
            delivery_date=D(6), purchase_date=D(8), is_bundle=True,
            items=[
                _item(sku="SKU-BU1", name="Kitchen Bundle - Mixer", category=ItemCategory.home,
                      price_cents=14000),
                _item(sku="SKU-BU2", name="Kitchen Bundle - Cookware", category=ItemCategory.home,
                      price_cents=8000),
            ],
        )],
    ),
    # ---- R2 + used item → denied (condition unacceptable) ----
    (
        "R2 used item denied",
        {"email": "sam.tate@example.com", "name": "Sam Tate", "token_last4": "5050"},
        [_order(
            order_number="WP-1019", subtotal_cents=6500, shipping_cents=500, total_cents=7000,
            delivery_date=D(18), purchase_date=D(20),
            items=[_item(sku="SKU-A6", name="Denim Jacket", price_cents=6500, reported_unused=False)],
        )],
    ),
    # ---- Retry demo: malformed input "WP 1020" should retry as WP-1020 ----
    (
        "Retry demo malformed order lookup",
        {"email": "retry.case@example.com", "name": "Riley Trace", "token_last4": "2020"},
        [_order(
            order_number="WP-1020", subtotal_cents=11800, shipping_cents=500, total_cents=12300,
            delivery_date=D(8), purchase_date=D(10),
            items=[_item(sku="SKU-R1", name="Canvas Weekender", category=ItemCategory.apparel,
                         price_cents=11800)],
        )],
    ),
]


def seed(session: Session) -> dict[str, int]:
    """Insert all cases. Idempotent on order_number + email. Returns counts."""
    customers_added = 0
    orders_added = 0
    items_added = 0

    for label, cust_data, orders in CASES:
        existing = session.scalar(select(Customer).where(Customer.email == cust_data["email"]))
        if existing:
            customer = existing
        else:
            customer = Customer(**cust_data)
            session.add(customer)
            session.flush()
            customers_added += 1

        for od in orders:
            od_data = dict(od)
            items_data = od_data.pop("items", [])
            existing_order = session.scalar(
                select(Order).where(Order.order_number == od_data["order_number"])
            )
            if existing_order:
                continue
            order = Order(customer_id=customer.id, **od_data)
            session.add(order)
            session.flush()
            orders_added += 1
            for it in items_data:
                session.add(OrderItem(order_id=order.id, **it))
                items_added += 1

    session.commit()
    return {"customers": customers_added, "orders": orders_added, "items": items_added}


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the WORPODD mock CRM DB")
    parser.add_argument("--reset", action="store_true", help="Drop + recreate tables first")
    args = parser.parse_args()

    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
        future=True,
    )
    if args.reset:
        Base.metadata.drop_all(engine)
        print("[seed] dropped existing tables")
    Base.metadata.create_all(engine)

    with SessionLocal() as session:
        counts = seed(session)
    print(f"[seed] done: {counts['customers']} customers, "
          f"{counts['orders']} orders, {counts['items']} items added")
    print(f"[seed] cases loaded: {len(CASES)}")


if __name__ == "__main__":  # pragma: no cover
    main()
