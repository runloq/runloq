"""FastAPI dependencies — DB connection lifecycle."""
from typing import Iterator
import sqlite3

from prism.prism import get_db as _open_db


def get_db() -> Iterator[sqlite3.Connection]:
    """Yield a tracker DB connection per request. Closed automatically.

    `get_db()` reads the tracker.DB_PATH module attribute at call time, so
    test harnesses that monkey-patch `tracker.DB_PATH = ...` work correctly.
    WAL mode + foreign keys are enabled by `get_db()` itself.
    """
    db = _open_db()
    try:
        yield db
    finally:
        db.close()
