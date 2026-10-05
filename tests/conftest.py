from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest


@pytest.fixture
def fixed_clock():
    """A deterministic clock fixture: returns a fixed UTC instant every call."""
    fixed_instant = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
    return lambda: fixed_instant


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_fry14_engine.duckdb"
