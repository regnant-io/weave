"""ORM models — the core data model from architecture.md section 9,
plus supporting tables (source chunks/embeddings, OTP codes, sandbox audit log).

Bilingual content is stored as first-class columns (`*_sw` / `*_en`), never as a
runtime translation pass — Design Principle 5.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Institution(Base):
    __tablename__ = "institutions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(32))  # secondary | university
    curriculum_tag: Mapped[str | None] = mapped_column(String(64), nullable=True)  # NECTA/CSEE

    users: Mapped[list["User"]] = relationship(back_populates="institution")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    phone: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="student")  # student|researcher|both
    institution_id: Mapped[str | None] = mapped_column(ForeignKey("institutions.id"), nullable=True)
    preferred_language: Mapped[str] = mapped_column(String(8), default="sw")  # sw | en
    trust_tier: Mapped[str] = mapped_column(String(16), default="verified")  # anon|verified|institutional
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    #: May the sources this user's sessions actually consult be queued for
    #: crawling into the shared library? ON by default — the library only gets
    #: richer if real use feeds it — and switchable off in Settings. Nothing is
    #: crawled from a user who turns this off, and nothing user-authored is ever
    #: ingested either way: only public pages the session already fetched.
    allow_source_crawl: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    institution: Mapped[Institution | None] = relationship(back_populates="users")
    projects: Mapped[list["Project"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class OtpCode(Base):
    __tablename__ = "otp_codes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    phone: Mapped[str] = mapped_column(String(32), index=True)
    code_hash: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Project(Base):
    """Persistent research memory (architecture section 9 / 6.2 project memory layer)."""
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(255))
    mode: Mapped[str] = mapped_column(String(16), default="student")  # student | researcher
    hypotheses: Mapped[list] = mapped_column(JSON, default=list)  # [{id,text_sw,text_en,status}]
    summary: Mapped[str] = mapped_column(Text, default="")  # rolling LLM summary
    notes: Mapped[list] = mapped_column(JSON, default=list)  # lit-review notes [{id,text,created_at}]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped[User] = relationship(back_populates="projects")
    datasets: Mapped[list["Dataset"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Message.created_at"
    )
    threads: Mapped[list["Thread"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Thread.created_at"
    )
    memory: Mapped[list["MemoryEntry"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    citations: Mapped[list["Citation"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    s3_key: Mapped[str] = mapped_column(String(512))
    original_filename: Mapped[str] = mapped_column(String(255))
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    column_profile: Mapped[dict] = mapped_column(JSON, default=dict)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="profiling")  # profiling|ready|error
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped[Project] = relationship(back_populates="datasets")


class Thread(Base):
    """One conversation inside a project.

    A project is the durable research workspace; a thread is a single line of
    enquiry within it. Splitting them is what allows a long investigation to be
    broken into readable conversations WITHOUT losing what earlier ones
    established — continuity lives in the project (summary + MemoryEntry), not
    in one ever-growing message list.

    It is also the unit of context management: when a thread's history no longer
    fits the selected model's window it is summarised and a successor thread is
    opened with `parent_thread_id` pointing back, so the chain stays auditable.
    """
    __tablename__ = "threads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    # Compact recap of this thread, written when it is rolled or on demand. This
    # is what later threads in the same project read.
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|archived|rolled
    # Set when this thread was opened automatically because its predecessor
    # filled the model's context window.
    parent_thread_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Running estimate of the tokens this thread's history occupies, so the
    # rollover decision doesn't require re-reading every message.
    token_estimate: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped["Project"] = relationship(back_populates="threads")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan", order_by="Message.created_at"
    )


class MemoryEntry(Base):
    """A durable fact the assistant chose to carry across threads.

    The rolling project summary is lossy by construction — it is a fixed-length
    window over a growing conversation, so specifics (a chosen method, a dataset
    quirk, a rejected approach) fall out of it exactly when they start
    mattering. These entries are the opposite: small, addressable, and never
    silently truncated. They are written by the `remember` tool and read back
    into the system prompt on every turn of every thread in the project.
    """
    __tablename__ = "project_memory"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    # Thread it originated in, so the UI can say where a fact came from.
    thread_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # fact | decision | preference | finding | question | artifact
    kind: Mapped[str] = mapped_column(String(24), default="fact")
    # Short stable slug. Writing the same key again UPDATES rather than
    # duplicating, so a corrected fact replaces the wrong one.
    key: Mapped[str] = mapped_column(String(96), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    # 1-5. Higher entries survive when the budget forces a trim.
    importance: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped["Project"] = relationship(back_populates="memory")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    # Nullable so pre-thread rows keep loading; init_db backfills them into a
    # default thread on first boot after the upgrade.
    thread_id: Mapped[str | None] = mapped_column(
        ForeignKey("threads.id"), nullable=True, index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content_sw: Mapped[str] = mapped_column(Text, default="")
    content_en: Mapped[str] = mapped_column(Text, default="")
    original_language: Mapped[str] = mapped_column(String(8), default="sw")
    tool_calls: Mapped[list] = mapped_column(JSON, default=list)
    citations: Mapped[list] = mapped_column(JSON, default=list)  # surfaced source refs
    artifacts: Mapped[list] = mapped_column(JSON, default=list)  # charts/decks/pdfs/3d
    images: Mapped[list] = mapped_column(JSON, default=list)     # top web-search images
    # The plan this turn worked to: {goal, steps:[{n,title,status,note}], checks}.
    # Empty for turns that did not need one (a greeting is not planned). Stored
    # so a reloaded conversation shows what was attempted and what was ticked
    # off — without it the ledger the user watched during the turn vanishes on
    # refresh, which is exactly how a progress display teaches people to ignore it.
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped[Project] = relationship(back_populates="messages")
    thread: Mapped["Thread | None"] = relationship(back_populates="messages")
    analysis_runs: Mapped[list["AnalysisRun"]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    dataset_id: Mapped[str | None] = mapped_column(ForeignKey("datasets.id"), nullable=True)
    code: Mapped[str] = mapped_column(Text)
    stdout: Mapped[str] = mapped_column(Text, default="")
    stderr: Mapped[str] = mapped_column(Text, default="")
    output_files: Mapped[list] = mapped_column(JSON, default=list)  # [{name, s3_key, mime, bytes}]
    execution_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # ok|error|rejected|timeout
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    message: Mapped[Message | None] = relationship(back_populates="analysis_runs")


class Source(Base):
    """Retrieval library entry (architecture section 7 / 9)."""
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(512))
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32))  # udsm|costech|nbs|journal|gov
    access_status: Mapped[str] = mapped_column(String(16), default="open")  # open | paywalled
    language: Mapped[str] = mapped_column(String(8), default="en")  # en | sw | mixed
    predatory_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    publication_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    chunks: Mapped[list["SourceChunk"]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class Canvas(Base):
    """A document the user and the assistant edit together, live.

    CONCURRENCY MODEL — read this before changing anything here.

    This is not a CRDT and does not pretend to be. It is server-authoritative
    with a monotonic `revision`, and the two parties are given different edit
    primitives because they edit in genuinely different ways:

      * The HUMAN sends whole-document writes carrying the `base_revision` their
        editor last saw. If that is stale the write is REJECTED with the current
        text, and the client resolves it. Nothing is silently overwritten.

      * The ASSISTANT sends ANCHORED edits — find/replace, append, insert near a
        heading. Those rebase naturally: they are applied to whatever the
        document currently says, and if the anchor has vanished the tool fails
        with a message the model can act on rather than clobbering the user's
        paragraph.

    That asymmetry is what makes simultaneous editing safe without character-wise
    transforms. A human typing in one paragraph and the assistant rewriting
    another do not conflict; a genuine overlap surfaces as a rejection instead of
    a silent loss.
    """
    __tablename__ = "canvases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="Untitled")
    content: Mapped[str] = mapped_column(Text, default="")
    #: Bumped on every accepted write. The whole concurrency scheme rests on it.
    revision: Mapped[int] = mapped_column(Integer, default=0)
    #: "human" | "assistant" — drives the "who changed this last" affordance.
    updated_by: Mapped[str] = mapped_column(String(16), default="human")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CrawlSeed(Base):
    """A starting point for the crawler, plus the politeness budget for it.

    Seeds are per-DOMAIN rather than per-URL because every limit that matters —
    request rate, page budget, robots.txt — is a property of the host, not of
    one address. Two seeds on the same host would otherwise each think they were
    the only one crawling it.

    `origin` records how the seed got here: "admin" for one an operator added,
    "session" for a domain a user's session actually consulted. That distinction
    is what makes the Settings opt-out meaningful — turning it off stops session
    seeds being created without touching the curated ones.
    """
    __tablename__ = "crawl_seeds"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    url: Mapped[str] = mapped_column(String(1024))
    domain: Mapped[str] = mapped_column(String(255), index=True)
    source_type: Mapped[str] = mapped_column(String(32), default="gov")
    language: Mapped[str] = mapped_column(String(8), default="en")
    #: admin | session
    origin: Mapped[str] = mapped_column(String(16), default="admin")
    #: The user whose session surfaced this domain, when origin == "session".
    discovered_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # --- politeness budget, per seed -------------------------------------
    max_depth: Mapped[int] = mapped_column(Integer, default=2)
    max_pages: Mapped[int] = mapped_column(Integer, default=40)
    #: Seconds between requests to this host. Below 1.0 is not polite.
    delay_seconds: Mapped[float] = mapped_column(Float, default=1.0)
    #: Stay on the seed's own domain. Off-domain crawling from a session-derived
    #: seed is how a focused library turns into a copy of the open web.
    same_domain_only: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Render with the headless browser before extracting (JS-heavy sites).
    render_js: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- state -----------------------------------------------------------
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|running|done|error
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0)
    pages_indexed: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CrawlPage(Base):
    """One URL the crawler considered, and what became of it.

    Kept for every outcome, not just successes: "why is this page not in the
    library" is the question an operator actually asks, and "it was disallowed
    by robots.txt" is only answerable if the refusal was recorded.

    It doubles as the visited-set across runs, so a re-crawl does not re-fetch
    everything it already has.
    """
    __tablename__ = "crawl_pages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    seed_id: Mapped[str] = mapped_column(ForeignKey("crawl_seeds.id"), index=True)
    url: Mapped[str] = mapped_column(String(1024), index=True)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    #: indexed | skipped_robots | skipped_type | skipped_thin | skipped_duplicate
    #: | error | pending_review
    status: Mapped[str] = mapped_column(String(24), default="pending_review")
    reason: Mapped[str] = mapped_column(String(255), default="")
    title: Mapped[str] = mapped_column(String(512), default="")
    #: Hash of the extracted text — near-identical pages under different URLs
    #: (print views, session ids, calendar pages) are the classic spider trap.
    content_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    chars: Mapped[int] = mapped_column(Integer, default=0)
    source_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SourceChunk(Base):
    """Chunked + embedded passage. Embedding stored as JSON float list for the
    SQLite dev path; pgvector's `vector` column is the production swap."""
    __tablename__ = "source_chunks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list] = mapped_column(JSON, default=list)

    source: Mapped[Source] = relationship(back_populates="chunks")


class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    style: Mapped[str] = mapped_column(String(16), default="APA")  # APA | Harvard | ...
    flagged_predatory: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_reference: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped[Project] = relationship(back_populates="citations")


class SandboxAudit(Base):
    """Audit log of every execution (architecture 8.4 item 5), stored separately
    from the execution path."""
    __tablename__ = "sandbox_audit"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dataset_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    result_hash: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16))
    execution_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    peak_memory_kb: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
