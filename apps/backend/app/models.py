"""ORM models for the WORPODD mock CRM.

Design notes:
- ``Enum`` columns are bound to Python ``enums`` so the policy engine works
  with typed values, not magic strings.
- ``token_last4`` stores only the last 4 digits of any payment instrument —
  never a full card/PAN. This is mock data, but the discipline matters.
- All monetary values are stored as integer **cents** to avoid float drift.
- ``refund_count_90d`` is denormalized for fast abuse checks (R10) and kept
  accurate by the same write path that records refunds.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base


# --------------------------------------------------------------------- enums


class OrderStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    cancelled = "cancelled"
    refunded = "refunded"


class ItemCategory(str, enum.Enum):
    apparel = "apparel"
    electronics = "electronics"
    furniture = "furniture"
    home = "home"
    beauty = "beauty"
    grocery = "grocery"
    digital = "digital"
    sports = "sports"
    jewelry = "jewelry"


class RefundReason(str, enum.Enum):
    unwanted = "unwanted"            # changed mind
    wrong_item = "wrong_item"        # WORPODD shipped wrong item
    defective = "defective"          # arrived broken / faulty
    damaged_shipping = "damaged_shipping"
    not_as_described = "not_as_described"
    late_delivery = "late_delivery"
    price_adjustment = "price_adjustment"


class RefundVerdict(str, enum.Enum):
    approved = "approved"
    approved_partial = "approved_partial"
    approved_store_credit = "approved_store_credit"
    manual_review = "manual_review"
    denied = "denied"


# ------------------------------------------------------------------ models


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    # Last 4 of payment method on file — never a full PAN.
    token_last4: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    # Denormalized for R10 abuse checks.
    refund_count_90d: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    orders: Mapped[list["Order"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Human-friendly, opaque identifier exposed to customers/agent.
    order_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)

    status: Mapped[OrderStatus] = mapped_column(SAEnum(OrderStatus), default=OrderStatus.paid)
    is_gift: Mapped[bool] = mapped_column(default=False)
    is_bundle: Mapped[bool] = mapped_column(default=False)

    # All money in integer cents.
    subtotal_cents: Mapped[int] = mapped_column(Integer)
    shipping_cents: Mapped[int] = mapped_column(Integer, default=0)
    total_cents: Mapped[int] = mapped_column(Integer)

    delivery_date: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    purchase_date: Mapped[datetime] = mapped_column(server_default=func.now())

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    customer: Mapped["Customer"] = relationship(back_populates="orders")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)

    sku: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[ItemCategory] = mapped_column(SAEnum(ItemCategory))

    price_cents: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer, default=1)

    # Condition flags used by the policy engine.
    is_final_sale: Mapped[bool] = mapped_column(default=False)
    is_perishable: Mapped[bool] = mapped_column(default=False)
    is_personalized: Mapped[bool] = mapped_column(default=False)
    is_intimate: Mapped[bool] = mapped_column(default=False)
    is_digital: Mapped[bool] = mapped_column(default=False)
    is_gift_card: Mapped[bool] = mapped_column(default=False)
    digital_accessed: Mapped[bool] = mapped_column(default=False)

    # Customer-reported at refund time.
    reported_unused: Mapped[bool] = mapped_column(default=True)
    has_original_packaging: Mapped[bool] = mapped_column(default=True)
    is_defective: Mapped[bool] = mapped_column(default=False)

    order: Mapped["Order"] = relationship(back_populates="items")


class RefundRecord(Base):
    """Append-only audit log of every refund decision the engine makes."""

    __tablename__ = "refund_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)

    verdict: Mapped[RefundVerdict] = mapped_column(SAEnum(RefundVerdict))
    reason: Mapped[RefundReason] = mapped_column(SAEnum(RefundReason), nullable=True)
    # Cents actually refunded (0 for denied/manual_review).
    refund_cents: Mapped[int] = mapped_column(Integer, default=0)
    # The clause IDs that drove the decision, e.g. ["R1", "R6"].
    clauses_hit: Mapped[str] = mapped_column(Text, default="")
    # Free-text rationale produced deterministically (not by the LLM).
    rationale: Mapped[str] = mapped_column(Text, default="")
    # Idempotency key: order_id + session. Prevents replay of an approval.
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
