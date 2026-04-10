"""
Synchronous database connection for Celery tasks.

Celery tasks run in a synchronous context (no event loop), so we use
psycopg2 directly rather than SQLAlchemy's async engine.
"""
import os
from contextlib import contextmanager
from collections.abc import Generator
from typing import Any

import psycopg2
import psycopg2.extras

DATABASE_URL = os.getenv("DATABASE_URL", "postgres://postgres:postgres@localhost:5432/discount_optimizer")


@contextmanager
def get_sync_db_connection() -> Generator[Any, None, None]:
    """
    Yields a psycopg2 connection. Rolls back and closes on exception.
    Always use as a context manager:

        with get_sync_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(...)
            conn.commit()
    """
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
