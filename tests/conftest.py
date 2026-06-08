from pathlib import Path

import pytest

import claudemon.db as db


@pytest.fixture
def conn():
    """In-memory SQLite connection with schema applied."""
    c = db.connect()
    yield c
    c.close()


FIXTURES_DIR = Path(__file__).parent / "fixtures"
