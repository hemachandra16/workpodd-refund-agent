"""Pytest config: shared fixtures for the backend test suite.

Uses an in-memory-ish temp SQLite file so tests never touch the dev DB.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Ensure the backend package is importable when running from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import Base, SessionLocal, engine as prod_engine  # noqa: E402
from app.data.seed import seed  # noqa: E402


@pytest.fixture(scope="session")
def seeded_db(tmp_path_factory):
    """Create a fresh SQLite file seeded with all cases, once per session."""
    db_file = tmp_path_factory.mktemp("worpodd") / "test.db"
    # Re-point the app's engine at the temp file for the duration of the session.
    test_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(test_engine)
    with Session(test_engine) as s:
        seed(s)
    return db_file


@pytest.fixture()
def db_session(seeded_db):
    """Yield a Session against the seeded test DB, rolled back after."""
    from sqlalchemy import create_engine as _ce

    eng = _ce(f"sqlite:///{seeded_db}", connect_args={"check_same_thread": False}, future=True)
    with Session(eng) as s:
        yield s
