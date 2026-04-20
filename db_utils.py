import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager

from app_errors import DatabaseBusyError

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "db", "attendance.db")
DB_PATH = os.getenv("ATTENDX_DB_PATH", DEFAULT_DB_PATH)

DEFAULT_TIMEOUT_SECONDS = float(os.getenv("ATTENDX_DB_TIMEOUT_SECONDS", "30"))
BUSY_TIMEOUT_MS = int(os.getenv("ATTENDX_DB_BUSY_TIMEOUT_MS", "30000"))
WRITE_RETRIES = int(os.getenv("ATTENDX_DB_WRITE_RETRIES", "5"))
WRITE_BACKOFF_SECONDS = float(os.getenv("ATTENDX_DB_WRITE_BACKOFF_SECONDS", "0.05"))
WRITE_BACKOFF_MAX_SECONDS = float(os.getenv("ATTENDX_DB_WRITE_BACKOFF_MAX_SECONDS", "1.0"))

logger = logging.getLogger("attendx.db")
_write_lock = threading.RLock()


class ManagedConnection(sqlite3.Connection):
    """sqlite3 connection that closes when used as a context manager."""

    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


def _is_lock_error(exc):
    text = str(exc).lower()
    return "database is locked" in text or "database is busy" in text or "locked" in text


def _ensure_db_dir():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)


def _configure_connection(conn):
    # WAL lets readers continue while one writer commits, which is critical for
    # camera polling plus dashboard/report reads.
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")


def get_db_connection(timeout=DEFAULT_TIMEOUT_SECONDS, row_factory=sqlite3.Row):
    """Return a configured SQLite connection.

    Existing scripts still call this directly. New code should prefer
    read_connection() or execute_write() so commits, rollbacks, and closes are
    consistently handled.
    """
    _ensure_db_dir()
    conn = sqlite3.connect(
        DB_PATH,
        timeout=timeout,
        isolation_level=None,
        factory=ManagedConnection,
    )
    if row_factory is not None:
        conn.row_factory = row_factory
    _configure_connection(conn)
    return conn


@contextmanager
def read_connection(row_factory=sqlite3.Row):
    conn = get_db_connection(row_factory=row_factory)
    try:
        logger.debug("DB read connection opened")
        yield conn
    except sqlite3.OperationalError as exc:
        logger.exception("DB read failed: %s", exc)
        if _is_lock_error(exc):
            raise DatabaseBusyError() from exc
        raise
    finally:
        conn.close()
        logger.debug("DB read connection closed")


def execute_write(operation, *, retries=WRITE_RETRIES):
    """Run a complete write transaction with retry and exponential backoff.

    The operation callable receives a connection. If SQLite reports a lock
    before commit, the whole operation is retried so callers do not persist
    partial state.
    """
    attempt = 0
    while True:
        with _write_lock:
            conn = get_db_connection()
            try:
                logger.debug("DB write transaction begin")
                conn.execute("BEGIN IMMEDIATE")
                result = operation(conn)
                conn.commit()
                logger.debug("DB write transaction commit")
                return result
            except sqlite3.OperationalError as exc:
                conn.rollback()
                if _is_lock_error(exc) and attempt < retries:
                    delay = min(
                        WRITE_BACKOFF_MAX_SECONDS,
                        WRITE_BACKOFF_SECONDS * (2 ** attempt),
                    )
                    logger.warning(
                        "DB write locked; retrying attempt=%s delay=%.3fs error=%s",
                        attempt + 1,
                        delay,
                        exc,
                    )
                    attempt += 1
                elif _is_lock_error(exc):
                    logger.exception("DB write lock retries exhausted")
                    raise DatabaseBusyError() from exc
                else:
                    logger.exception("DB write failed")
                    raise
            except sqlite3.IntegrityError:
                conn.rollback()
                logger.warning("DB write integrity constraint failed")
                raise
            except Exception:
                conn.rollback()
                logger.exception("DB write transaction rollback")
                raise
            finally:
                conn.close()
                logger.debug("DB write connection closed")

        time.sleep(delay)


@contextmanager
def write_transaction():
    """Single-attempt write transaction for scripts that need context syntax."""
    with _write_lock:
        conn = get_db_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
