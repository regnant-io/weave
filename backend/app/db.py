"""Database engine + session.

architecture.md section 2 specifies PostgreSQL 16 + pgvector. For a zero-service
dev/prototype boot we default to SQLite; the ORM models and the retrieval layer
are written so a Postgres URL is a drop-in swap (WEAVE_DATABASE_URL=postgresql://...).
Vector search is abstracted in services/retrieval so pgvector can replace the
SQLite numpy-cosine path without touching callers.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

# timeout = how long SQLite waits for a write lock before erroring. The streaming
# worker-thread model holds transactions longer, so concurrent turns can contend;
# a generous busy timeout makes writers queue instead of failing with
# "database is locked". (Postgres has no single-writer limit — this is a
# SQLite-dev-path concern only.)
_connect_args = {"check_same_thread": False, "timeout": 30} if settings.is_sqlite else {}

engine = create_engine(
    settings.database_url,
    echo=False,
    future=True,
    connect_args=_connect_args,
)


if settings.is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")  # wait up to 30s for a write lock
        cur.execute("PRAGMA synchronous=NORMAL")  # safe with WAL, less fsync contention
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yields a session, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables and the FTS5 index used by the Retrieval Service."""
    from . import models  # noqa: F401  (register mappers)

    Base.metadata.create_all(bind=engine)

    if settings.is_sqlite:
        from sqlalchemy import text
        with engine.begin() as conn:
            # BM25 half of the hybrid retrieval (architecture 7.3) via SQLite FTS5.
            conn.execute(text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS source_chunk_fts "
                "USING fts5(chunk_id UNINDEXED, content, tokenize='unicode61')"
            ))
            # Lightweight auto-migration: add columns create_all won't add to an
            # existing table (SQLite). Safe to run every boot.
            mcols = {r[1] for r in conn.execute(text("PRAGMA table_info(messages)"))}
            for col in ("artifacts", "images"):
                if col not in mcols:
                    conn.execute(text(f"ALTER TABLE messages ADD COLUMN {col} JSON DEFAULT '[]'"))
            pcols = {r[1] for r in conn.execute(text("PRAGMA table_info(projects)"))}
            if "notes" not in pcols:
                conn.execute(text("ALTER TABLE projects ADD COLUMN notes JSON DEFAULT '[]'"))
