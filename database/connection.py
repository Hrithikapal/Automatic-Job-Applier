"""
database/connection.py — Database engine, session factory, and helpers.

Usage:
    from database.connection import init_db, get_session, get_session_factory

    # Create all tables (call once at startup)
    init_db()

    # Use as a context manager for a single operation
    with get_session() as session:
        user = session.get(User, 1)

    # Get a factory for dependency injection (e.g. queue manager)
    session_factory = get_session_factory()
    with session_factory() as session:
        ...
"""
import os
from contextlib import contextmanager
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

from database.models import Base

load_dotenv()

_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ai_job_applier.db")

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

_engine = create_engine(
    _DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in _DATABASE_URL else {},
    echo=False,
)

# Enable WAL mode for SQLite — better concurrent read performance
if "sqlite" in _DATABASE_URL:
    @event.listens_for(_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

_SessionFactory = sessionmaker(
    bind=_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def init_db() -> None:
    """Create all tables. Safe to call multiple times (uses CREATE IF NOT EXISTS)."""
    Base.metadata.create_all(_engine)


def get_session_factory() -> sessionmaker:
    """Return the session factory (for dependency injection)."""
    return _SessionFactory


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Context manager that provides a database session and handles
    commit/rollback automatically.

    Example:
        with get_session() as session:
            session.add(User(...))
            session.commit()
    """
    session: Session = _SessionFactory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
