"""Synchronous psycopg pool, used only from threadpool-backed handlers."""

import logging
import threading
from contextlib import contextmanager

from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from app.core.config import get_settings

logger = logging.getLogger("insighthub.db")
_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def _configure(conn):
    register_vector(conn)
    conn.commit()  # Pool configure callbacks must leave the connection idle.


def get_pool() -> ConnectionPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ConnectionPool(
                conninfo=get_settings().database_url,
                min_size=2,
                max_size=10,
                configure=_configure,
                timeout=10,
                open=True,
            )
    return _pool


@contextmanager
def get_conn():
    with get_pool().connection() as conn:
        yield conn


def initialize_database():
    from app.core.index import check_schema, ensure_index_identity

    get_pool().wait(timeout=15)
    with get_conn() as conn:
        check_schema(conn)
        ensure_index_identity(conn, claim=False)


def healthcheck() -> bool:
    try:
        from app.core.index import check_schema, ensure_index_identity

        with get_conn() as conn:
            check_schema(conn)
            ensure_index_identity(conn, claim=False)
        return True
    except Exception:
        logger.warning("Database readiness check failed")
        return False


def close_pool():
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None
