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
            if "thread_id" not in mcols:
                # No FK constraint in the ALTER: SQLite cannot add one after the
                # fact, and create_all has already declared it for fresh DBs.
                conn.execute(text("ALTER TABLE messages ADD COLUMN thread_id VARCHAR(32)"))
            pcols = {r[1] for r in conn.execute(text("PRAGMA table_info(projects)"))}
            if "notes" not in pcols:
                conn.execute(text("ALTER TABLE projects ADD COLUMN notes JSON DEFAULT '[]'"))
            # Consent for contributing session sources to the shared library.
            # Defaults to 1 (on) for existing users, matching the column default
            # and the documented behaviour — it is switchable in Settings.
            ucols = {r[1] for r in conn.execute(text("PRAGMA table_info(users)"))}
            if "allow_source_crawl" not in ucols:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN allow_source_crawl BOOLEAN DEFAULT 1"
                ))

    _backfill_threads()


def _backfill_threads() -> None:
    """Give every pre-thread message a home.

    Threads were introduced after messages existed. A message with a NULL
    thread_id would simply vanish from the UI (which now lists by thread), so
    each project with orphaned messages gets one thread holding its full prior
    history. Idempotent: after the first run there is nothing left to adopt.
    """
    import uuid
    from datetime import datetime, timezone

    from sqlalchemy import text

    with engine.begin() as conn:
        try:
            orphan_projects = [
                r[0] for r in conn.execute(text(
                    "SELECT DISTINCT project_id FROM messages WHERE thread_id IS NULL"
                ))
            ]
        except Exception:  # noqa: BLE001 - messages table not created yet
            return

        now = datetime.now(timezone.utc)
        for project_id in orphan_projects:
            if not project_id:
                continue
            existing = conn.execute(
                text("SELECT id FROM threads WHERE project_id = :p ORDER BY created_at LIMIT 1"),
                {"p": project_id},
            ).first()
            thread_id = existing[0] if existing else uuid.uuid4().hex
            if not existing:
                conn.execute(
                    text(
                        "INSERT INTO threads (id, project_id, title, summary, status, "
                        "parent_thread_id, token_estimate, created_at, updated_at) "
                        "VALUES (:id, :p, :t, '', 'active', NULL, 0, :c, :c)"
                    ),
                    {"id": thread_id, "p": project_id, "t": "Main thread", "c": now},
                )
            conn.execute(
                text("UPDATE messages SET thread_id = :t WHERE project_id = :p AND thread_id IS NULL"),
                {"t": thread_id, "p": project_id},
            )
