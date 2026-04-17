"""
Synchronous SQLAlchemy database session factory for Celery workers.
"""

import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_engine = None
_SessionFactory = None


def _get_database_url() -> str:
    """Convert DATABASE_URL to psycopg2 format if needed."""
    url = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/vre")
    # asyncpg / postgres:// → psycopg2
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://") and "+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    return url


def _init_engine():
    global _engine, _SessionFactory
    if _engine is None:
        db_url = _get_database_url()
        _engine = create_engine(
            db_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=300,
        )
        _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False)
        logger.info("Database engine initialized")


@contextmanager
def get_session():
    """
    Context manager that yields a SQLAlchemy Session and commits on success,
    rolls back on exception.

    Usage:
        with get_session() as session:
            session.execute(...)
    """
    _init_engine()
    session: Session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
