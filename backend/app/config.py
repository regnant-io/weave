"""Runtime configuration.

Everything is overridable via environment variables (12-factor). Defaults are
chosen so the whole platform boots with **zero external services** — the point
of the MVP prototype tier in architecture.md section 13 (v0).
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "var"
DATA_DIR.mkdir(exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WEAVE_", env_file=".env", extra="ignore")

    # --- app ---
    app_name: str = "Weave"
    environment: str = "dev"  # dev | staging | production
    debug: bool = True
    api_prefix: str = "/api/v1"

    # --- security ---
    # NOTE: override WEAVE_SECRET_KEY in production. A random per-process key
    # would invalidate tokens on restart, so we ship a stable dev default.
    secret_key: str = "dev-insecure-change-me-in-production-please-0123456789"
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 60 * 60 * 24 * 7  # 7 days
    otp_ttl_seconds: int = 60 * 10

    # --- database ---
    # Production: postgresql+psycopg://... with pgvector. Dev default: SQLite.
    database_url: str = f"sqlite:///{(DATA_DIR / 'weave.db').as_posix()}"

    # --- object storage (S3-compatible). Dev default: local filesystem. ---
    storage_backend: str = "local"  # local | s3
    storage_local_dir: str = str(DATA_DIR / "storage")
    s3_bucket: str = "weave-datasets"
    s3_endpoint_url: str | None = None
    s3_region: str = "af-south-1"  # data-residency-aware default (architecture 10)

    # --- LLM ---
    # Backend selection (see llm.get_engine):
    #   auto      -> Ollama if reachable, else Anthropic if a key is set, else offline
    #   ollama    -> force Ollama (falls back to offline if unreachable)
    #   anthropic -> force Anthropic (falls back to offline if no key/SDK)
    #   offline   -> force the deterministic offline engine
    llm_backend: str = "auto"
    # Output ceiling for the Anthropic path. Deliberately generous: a truncated
    # answer mid-file is worse than a slow one, and this is a ceiling, not a target.
    llm_max_tokens: int = 16384
    # Agentic tool loop: allow long autonomous runs (a single prompt can legitimately
    # run for a long time on hard work — don't cap it artificially).
    llm_max_tool_iters: int = 40
    # When set, always use the deterministic offline engine (used by CI/tests).
    force_offline_llm: bool = False

    # Anthropic (Claude)
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    model_tier_fast: str = "claude-haiku-4-5-20251001"
    model_tier_frontier: str = "claude-opus-4-8"

    # Ollama (fully-local LLM). host.docker.internal is set in docker-compose so a
    # containerised backend reaches an Ollama server running on the host.
    ollama_host: str = os.getenv("WEAVE_OLLAMA_HOST", "http://localhost:11434")
    ollama_model: str = "llama3.1"            # must be a tool-capable model
    ollama_model_fast: str | None = None      # defaults to ollama_model
    ollama_model_frontier: str | None = None  # defaults to ollama_model
    ollama_request_timeout: int = 600         # long runs allowed
    # Fallback context window, used ONLY when the model's real window can't be
    # read from /api/show. It is not a cap: clamping every model to this was
    # throwing away 97% of a 262k-token window and reporting "8.2k" in the UI.
    ollama_num_ctx: int = 8192
    # Optional upper bound on what we request from a model that advertises a very
    # large window. 0 (the default) means NO CEILING — every model gets its own
    # full window. A previous default of 32768 silently clamped a 262k model to
    # 32k, which is exactly what truncated long file generation. Set a positive
    # value only if a metered endpoint makes huge contexts costly.
    ollama_max_num_ctx: int = 0
    # Hard floor so a model that mis-reports a tiny window still gets usable room.
    ollama_min_num_ctx: int = 4096
    # Fraction of the context window left free for the model's OWN output when
    # deciding num_predict. The rest is assumed to be prompt + history.
    ollama_output_reserve: float = 0.4
    # Ollama embeddings for retrieval (opt-in; needs the embed model pulled). When
    # off, the deterministic offline embedding is used (keeps a zero-dependency boot).
    ollama_use_embeddings: bool = False
    ollama_embed_model: str = "nomic-embed-text"

    # --- retrieval ---
    embedding_dim: int = 384  # matches a small multilingual model's dim
    retrieval_top_k: int = 6
    rrf_k: int = 60  # reciprocal-rank-fusion constant

    # --- deep web search (self-hosted services; all optional) ---
    # SearXNG metasearch (JSON API). Empty -> web search tool reports unavailable.
    searxng_url: str | None = os.getenv("WEAVE_SEARXNG_URL")
    # Browserless / Playwright headless-Chrome pool for JS-rendered fetches.
    browserless_url: str | None = os.getenv("WEAVE_BROWSERLESS_URL")
    websearch_max_results: int = 8
    websearch_fetch_timeout: int = 20
    websearch_max_pages: int = 4          # pages deep-read per research round
    research_max_rounds: int = 3          # iterative search->read->gap rounds
    research_max_fetch_bytes: int = 2_000_000

    # --- visual / presentation rendering (self-hosted) ---
    # Node render-sandbox HTTP service (charts, Three.js, decks).
    render_service_url: str | None = os.getenv("WEAVE_RENDER_URL")
    # Gotenberg for deterministic HTML/Markdown -> PDF.
    gotenberg_url: str | None = os.getenv("WEAVE_GOTENBERG_URL")

    # --- warehouse (mass data analysis) ---
    clickhouse_url: str | None = os.getenv("WEAVE_CLICKHOUSE_URL")

    # --- artifact lifecycle + per-turn safety ---
    artifact_ttl_seconds: int = 60 * 60 * 24 * 3   # keep generated artifacts 3 days
    artifact_sweep_interval_seconds: int = 60 * 60
    max_sandbox_runs_per_turn: int = 6
    max_web_calls_per_turn: int = 12
    # The workspace container is the most expensive capability per call, and a
    # looping agent could otherwise start hundreds of them in one turn.
    max_workspace_execs_per_turn: int = 40

    # --- sandbox (architecture section 8) ---
    sandbox_backend: str = "subprocess"  # subprocess | firecracker
    sandbox_timeout_seconds: int = 30
    sandbox_heavy_timeout_seconds: int = 120
    sandbox_memory_mb: int = 512
    sandbox_output_max_bytes: int = 10 * 1024 * 1024  # 10 MB (architecture 8.4)
    sandbox_max_output_files: int = 12

    # --- developer workspace (the SECOND sandbox; see services/workspace) ---
    # A persistent, network-enabled, per-project directory the model builds
    # software in. Deliberately separate from the analysis sandbox, which must
    # keep its no-network / no-filesystem guarantees around user data.
    workspace_enabled: bool = True
    workspace_root: str = str(DATA_DIR / "workspaces")
    workspace_image: str = os.getenv("WEAVE_WORKSPACE_IMAGE", "weave-workspace:latest")
    # Execution is containerised; without a container runtime the workspace
    # tools are not advertised at all rather than silently no-oping.
    workspace_memory_mb: int = 2048
    workspace_cpus: float = 2.0
    workspace_pids_limit: int = 512
    workspace_user: str = "1000:1000"           # never root inside the container
    workspace_exec_timeout: int = 180           # default per command
    workspace_exec_max_timeout: int = 1800      # ceiling a build may request
    workspace_output_chars: int = 20_000        # per stream, tail-truncated
    workspace_package_max_bytes: int = 80 * 1024 * 1024
    # Network access is what makes dependency installation and asset downloads
    # possible. It is the reason this sandbox is separate from the analysis one.
    workspace_network: bool = True
    workspace_network_mode: str = "bridge"

    # --- rate limiting (token bucket; architecture 5.3) ---
    rate_limit_chat_per_min: int = 20
    rate_limit_sandbox_per_min: int = 6
    rate_limit_anon_per_min: int = 10

    # --- cors ---
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # --- background jobs / cache (Redis + Celery) ---
    redis_url: str | None = os.getenv("WEAVE_REDIS_URL")   # e.g. redis://redis:6379/0
    celery_always_eager: bool = False  # run tasks inline when True or no redis

    # --- observability (OpenTelemetry) ---
    otel_enabled: bool = bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))
    otel_exporter_otlp_endpoint: str | None = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    otel_service_name: str = "weave-backend"

    # --- SMS (OTP delivery) ---
    sms_provider: str = "log"  # log | africastalking
    at_username: str | None = os.getenv("WEAVE_AT_USERNAME")
    at_api_key: str | None = os.getenv("WEAVE_AT_API_KEY")
    at_sender_id: str | None = os.getenv("WEAVE_AT_SENDER_ID")

    # --- WhatsApp channel (architecture §11 v2) ---
    whatsapp_verify_token: str = os.getenv("WEAVE_WA_VERIFY_TOKEN", "weave-verify")
    whatsapp_token: str | None = os.getenv("WEAVE_WA_TOKEN")
    whatsapp_phone_id: str | None = os.getenv("WEAVE_WA_PHONE_ID")

    @field_validator("database_url", mode="before")
    @classmethod
    def _default_sqlite(cls, v):  # noqa: ANN001
        # An empty env value (compose passes ${WEAVE_DATABASE_URL:-}) must not blank
        # out the DB — fall back to the SQLite default.
        if not v or not str(v).strip():
            return f"sqlite:///{(DATA_DIR / 'weave.db').as_posix()}"
        return v

    @field_validator("redis_url", "otel_exporter_otlp_endpoint", "searxng_url",
                     "browserless_url", "render_service_url", "gotenberg_url",
                     "clickhouse_url", "anthropic_api_key", "whatsapp_token",
                     "whatsapp_phone_id", "at_username", "at_api_key", mode="before")
    @classmethod
    def _empty_to_none(cls, v):  # noqa: ANN001
        return None if (v is not None and not str(v).strip()) else v

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
