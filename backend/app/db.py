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

#: Pool configuration, for Postgres only.
#:
#: SQLite gets none of it: it uses SQLAlchemy's SingletonThreadPool/NullPool and
#: passing `pool_size` to that raises. The distinction is not cosmetic — the two
#: engines have genuinely different scarce resources. SQLite's is the single
#: write lock; Postgres' is the connection count.
_pool_args: dict = {}
if not settings.is_sqlite:
    _pool_args = {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout,
        "pool_recycle": settings.db_pool_recycle_seconds,
        # CHECK THE CONNECTION IS ALIVE BEFORE HANDING IT OUT.
        #
        # Without this, a connection that a network blip, a proxy idle-timeout
        # or a database restart has already closed is handed to a request, which
        # then fails on its first statement with a driver-level error nobody can
        # do anything about. It costs one round trip per checkout and removes an
        # entire class of intermittent 500s — the kind that appear in production
        # under real network conditions and never once in development.
        "pool_pre_ping": True,
    }

engine = create_engine(
    settings.database_url,
    echo=False,
    future=True,
    connect_args=_connect_args,
    **_pool_args,
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


def release(db: Session) -> None:
    """Return this session's connection to the pool without closing the session.

    THE POOL PROBLEM THIS SOLVES

    A `Session` checks a connection out of the pool when a transaction begins
    and returns it on commit or rollback. In "commit as you go" mode a plain
    SELECT opens a transaction too — so a single `db.query(...)` early in a turn
    holds a connection for the ENTIRE turn, through minutes of model generation
    and tool calls that need no database at all.

    With SQLite that is the single write lock, and the second student to send a
    message waits for the first to finish thinking. With Postgres it is a
    connection, and a hundred simultaneous turns is a hundred connections held
    almost entirely idle — the pool is exhausted by conversations that are not
    using it.

    Calling this after any database work that is complete hands the connection
    back. The session stays usable; the next statement checks one out again.
    Loaded objects survive because `expire_on_commit=False`, so callers keep
    working with what they already read.
    """
    try:
        if db.in_transaction():
            # Commit rather than rollback: a tool that wrote something has
            # already finished its own unit of work, and rolling that back here
            # would silently discard it.
            db.commit()
    except Exception:  # noqa: BLE001 - releasing must never be the thing that fails
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass


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
            # The supervised loop's plan ledger. Object, not array — hence its
            # own line rather than joining the loop above.
            if "plan" not in mcols:
                conn.execute(text("ALTER TABLE messages ADD COLUMN plan JSON DEFAULT '{}'"))
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

    else:
        _init_postgres()

    _backfill_threads()


def _init_postgres() -> None:
    """The Postgres half of schema setup.

    `create_all` builds the tables, and everything else here was previously
    written only for SQLite -- so a Postgres deployment came up with no
    full-text index and no way to pick up a column added after its database was
    created. The first of those is a silent performance cliff (see
    retrieval/service.py: without the stored vector every keyword search is a
    sequential scan of the whole corpus); the second is a hard failure on the
    first query that mentions the new column.

    Every statement is IF NOT EXISTS and safe to run on every boot. It is not a
    migration system and does not pretend to be one -- it is the same
    "add what is missing" pass the SQLite branch already does, so that moving a
    running instance forward does not require one.
    """
    from sqlalchemy import text

    statements = [
        # pgvector, for the dense half of retrieval. Harmless if the extension
        # is already there; a no-op on an image that lacks it, which is why the
        # whole block is tolerant rather than fatal.
        "CREATE EXTENSION IF NOT EXISTS vector",
        # Columns added after the first deployments. `create_all` adds them to a
        # NEW database and cannot add them to an existing one.
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS artifacts JSON DEFAULT '[]'",
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS images JSON DEFAULT '[]'",
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS plan JSON DEFAULT '{}'",
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS thread_id VARCHAR(32)",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS notes JSON DEFAULT '[]'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS allow_source_crawl BOOLEAN DEFAULT TRUE",
        # The keyword half of hybrid retrieval. A STORED generated column plus a
        # GIN index, which is the Postgres equivalent of the FTS5 virtual table
        # the SQLite branch creates -- and the thing that makes the query in
        # `_sparse_search_pg` an index lookup instead of a table scan.
        "ALTER TABLE source_chunks ADD COLUMN IF NOT EXISTS content_ts tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED",
        "CREATE INDEX IF NOT EXISTS source_chunk_ts_idx ON source_chunks USING GIN (content_ts)",
        # The lookups every turn makes, in the order they hurt without an index.
        "CREATE INDEX IF NOT EXISTS messages_thread_created_idx "
        "ON messages (thread_id, created_at)",
        "CREATE INDEX IF NOT EXISTS messages_project_created_idx "
        "ON messages (project_id, created_at)",
        "CREATE INDEX IF NOT EXISTS threads_project_updated_idx "
        "ON threads (project_id, updated_at DESC)",
    ]

    for sql in statements:
        # Each in its own transaction: one failure (an extension the image does
        # not ship, a table a future refactor renamed) must not abort the rest
        # and leave the database half-prepared.
        try:
            with engine.begin() as conn:
                conn.execute(text(sql))
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger("weave.db").warning(
                "postgres setup step failed (continuing): %s -- %s", sql[:70], exc,
            )


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
