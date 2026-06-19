"""Database session + engine (SQLAlchemy).

Models land in Phase 2. For now this exposes a session factory so later
modules can be wired against a stable surface. Uses parameterized queries
exclusively — no raw string SQL anywhere in the codebase.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

# check_same_thread=False is fine behind FastAPI's per-request sessions.
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yields a scoped DB session, always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
