"""Pydantic request/response schemas.

Every payload carries an explicit `language` field where relevant — never
inferred silently (architecture 5.2).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Language = Literal["sw", "en"]
Mode = Literal["student", "researcher"]


# --- auth ---
class RegisterRequest(BaseModel):
    phone: str = Field(..., examples=["+255700000000"])
    password: str = Field(..., min_length=8)
    email: str | None = None
    role: Literal["student", "researcher", "both"] = "student"
    preferred_language: Language = "sw"
    institution_id: str | None = None


class LoginRequest(BaseModel):
    phone: str
    password: str


class OtpRequestBody(BaseModel):
    phone: str


class OtpVerifyBody(BaseModel):
    phone: str
    code: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    phone: str | None
    email: str | None
    role: str
    preferred_language: str
    trust_tier: str
    phone_verified: bool
    institution_id: str | None
    #: May the public sources this user's sessions consult be offered as crawl
    #: candidates for the shared library? On by default, switchable in Settings.
    allow_source_crawl: bool = True


class UserPrefsIn(BaseModel):
    """Partial update of the signed-in user's own preferences."""
    preferred_language: str | None = None
    allow_source_crawl: bool | None = None


# --- projects ---
class ProjectCreate(BaseModel):
    title: str
    mode: Mode = "student"


class HypothesisIn(BaseModel):
    text_sw: str = ""
    text_en: str = ""
    status: Literal["open", "supported", "refuted"] = "open"


class ProjectUpdate(BaseModel):
    title: str | None = None
    mode: Mode | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    mode: str
    hypotheses: list[dict[str, Any]]
    summary: str
    notes: list[dict[str, Any]] = []
    created_at: datetime


# --- threads (chats within a project) ---
class ThreadCreate(BaseModel):
    title: str = ""


class ThreadUpdate(BaseModel):
    title: str | None = None
    status: Literal["active", "archived"] | None = None


class ThreadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    title: str
    summary: str
    status: str
    parent_thread_id: str | None = None
    token_estimate: int = 0
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


# --- shared project memory ---
class MemoryEntryIn(BaseModel):
    key: str
    content: str
    kind: Literal["fact", "decision", "preference", "finding", "question", "artifact"] = "fact"
    importance: int = 3


class MemoryEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    key: str
    content: str
    kind: str
    importance: int
    thread_id: str | None = None
    created_at: datetime
    updated_at: datetime


# --- assistant -> user questions ---
class InteractionAnswer(BaseModel):
    #: question text -> chosen label(s). A free-typed answer is just another
    #: value here, so the model sees one uniform shape.
    answers: dict[str, str] = {}
    notes: str = ""


# --- datasets ---
class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    original_filename: str
    row_count: int | None
    column_profile: dict[str, Any]
    size_bytes: int
    status: str
    uploaded_at: datetime


# --- messages / chat ---
class MessageCreate(BaseModel):
    content: str
    language: Language = "sw"
    dataset_id: str | None = None
    # Which chat inside the project this turn belongs to. Omitted -> the
    # project's active thread, so older clients keep working unchanged.
    thread_id: str | None = None
    stream: bool = True
    effort: Literal["spool", "weave", "tapestry"] = "weave"
    model: str | None = None  # optional Ollama model override for this turn
    regenerate: bool = False   # reuse last user turn, drop the previous answer
    # Services the user switched on in the composer ({"web_search": true, ...}).
    # An explicit toggle outranks the intent router's guess for this turn.
    services: dict[str, bool] | None = None


class OllamaConfig(BaseModel):
    host: str | None = None
    model: str | None = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    role: str
    content_sw: str
    content_en: str
    original_language: str
    tool_calls: list[Any]
    citations: list[Any]
    artifacts: list[Any] = []
    images: list[Any] = []
    # The supervised loop's plan ledger for this turn ({} when it had none).
    plan: dict[str, Any] = {}
    created_at: datetime


# --- analysis ---
class AnalysisRunRequest(BaseModel):
    dataset_id: str
    code: str
    heavy: bool = False


class AnalysisRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    status: str
    stdout: str
    stderr: str
    output_files: list[Any]
    execution_time_ms: int


# --- library / retrieval ---
class SourcePassage(BaseModel):
    source_id: str
    chunk_id: str
    title: str
    url: str | None
    source_type: str
    access_status: str
    language: str
    predatory_flag: bool
    content: str
    score: float


class LibrarySearchResponse(BaseModel):
    query: str
    language: str
    results: list[SourcePassage]


# --- citations ---
class CitationCheckRequest(BaseModel):
    reference: str
    source_id: str | None = None
    style: Literal["APA", "Harvard", "Chicago", "IEEE"] = "APA"


class CitationCheckResponse(BaseModel):
    reference: str
    flagged_predatory: bool
    reason: str
    matched_source: SourcePassage | None = None


# --- steering: redirecting a turn that is still running ---
class SteerIn(BaseModel):
    text: str
    #: "redirect" (change direction), "focus" (go deeper on this), "skip" (drop
    #: what you are doing). Purely a UI label — the model receives the text.
    kind: str = "redirect"


# --- collaborative canvas ---
class CanvasOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    title: str
    content: str
    revision: int
    updated_at: datetime
    updated_by: str


class CanvasPatchIn(BaseModel):
    """A human edit.

    `base_revision` is what the editor last saw. The server rejects a write built
    on a stale revision rather than overwriting whatever landed in between — see
    services/canvas.py.
    """
    content: str
    base_revision: int
    title: str | None = None


TokenResponse.model_rebuild()
