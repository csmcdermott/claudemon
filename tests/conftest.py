import sqlite3
from pathlib import Path

import pytest

import claudemon.db as db


@pytest.fixture
def conn():
    """In-memory SQLite connection with schema applied."""
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript(db.SCHEMA)
    yield c
    c.close()


FIXTURES_DIR = Path(__file__).parent / "fixtures"
