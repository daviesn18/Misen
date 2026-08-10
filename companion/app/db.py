"""Database engine and session management.

SQLite for v1 (PRD §4). WAL mode is set on every connection: it lets readers
proceed while a write is in flight, which matters because the nightly backup
reads the database while the app is serving.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base. Models arrive in phase 1; Alembic autogenerate reads
    this metadata, so it must be importable even while empty."""


settings = get_settings()

engine = create_engine(
    settings.database_url,
    # SQLite refuses cross-thread use of a connection by default; FastAPI's
    # threadpool hands the same session to a worker thread.
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(Engine, "connect")
def _configure_sqlite(dbapi_connection, connection_record) -> None:  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    # Enforce the FK constraints the schema declares. SQLite ignores them
    # unless asked, which turns household_id references into decoration.
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a session per request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
