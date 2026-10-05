"""
Database engine/session setup. Deliberately lazy: importing this module must
not fail or connect to anything when PAHAADSHIELD_DATABASE_URL / (now)
GIRIVARSHA_DATABASE_URL is unset — Phase 1's endpoints and tests still need
to run without a database configured.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal: sessionmaker | None = None


class DatabaseNotConfiguredError(RuntimeError):
    pass


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        if not settings.database_url:
            raise DatabaseNotConfiguredError(
                "GIRIVARSHA_DATABASE_URL is not set. Copy backend/.env.example to "
                "backend/.env and set it, or export it directly. See README.md."
            )
        _engine = create_engine(settings.database_url, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    SessionLocal = get_sessionmaker()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    SessionLocal = get_sessionmaker()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
