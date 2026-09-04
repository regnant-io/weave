"""FastAPI application — the Gateway (architecture 5.1 #1).

The only publicly exposed service: auth, request validation, rate limiting, and
routing to Orchestration / Retrieval / Analysis. In this single-process MVP boot
the other three services run in-process behind the same app; the module
boundaries (app.services.*) keep them independently extractable later.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import api_router
from .config import settings
from .db import init_db
from .services.orchestration.llm import get_engine

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("weave")


def _artifact_sweeper() -> None:
    """Background GC for generated artifacts (charts/decks/pdfs/3d)."""
    import threading
    import time

    def loop() -> None:
        from .storage import storage
        while True:
            time.sleep(settings.artifact_sweep_interval_seconds)
            try:
                for prefix in ("render", "analysis"):
                    n = storage.sweep_prefix(prefix, settings.artifact_ttl_seconds)
                    if n:
                        log.info("artifact sweep: removed %d stale files under %s/", n, prefix)
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=loop, daemon=True).start()


_DEV_SECRET = "dev-insecure-change-me-in-production-please-0123456789"


def _preflight() -> None:
    """Refuse to run a production deployment with development defaults.

    This exists because the failure is silent and total: the shipped
    `secret_key` is public in the repository, so anyone who reads it can mint a
    valid JWT for any user on an exposed instance. A tunnelled dev box is
    exactly the situation where nobody remembers to set it, so the check is a
    hard stop rather than a warning.
    """
    is_prod = settings.environment.lower() in {"production", "prod", "staging"}
    problems: list[str] = []

    if settings.secret_key == _DEV_SECRET:
        msg = ("WEAVE_SECRET_KEY is still the public development default — anyone "
               "can forge a login token.")
        if is_prod:
            problems.append(msg)
        else:
            log.warning("SECURITY: %s Set it before exposing this instance.", msg)

    if is_prod and settings.debug:
        problems.append("WEAVE_DEBUG is on in a production environment.")

    # SQLite in production is not a configuration, it is an accident.
    #
    # It has exactly one writer, so two people sending a message at the same
    # moment serialise and a third waits behind both. That is invisible in
    # testing with one user and is the whole experience with a class of them --
    # and it presents as "the model is slow", which sends everyone looking in
    # the wrong place. Loud rather than fatal: an instance already running this
    # way should keep running while someone moves it.
    if settings.is_sqlite:
        msg = ("the database is SQLite, which serialises every write. Two users "
               "sending a message at the same time will queue behind each other. "
               "Set WEAVE_DATABASE_URL to a postgresql+psycopg:// URL.")
        if is_prod:
            log.error("CAPACITY: %s", msg)
        else:
            log.info("Using SQLite (development default). %s", msg)

    # Rate limits that only bind inside one process are not rate limits once
    # there is more than one worker, and nothing about the running system makes
    # that visible -- the configured number stays in the settings and stops
    # being true. See ratelimit.py.
    if not settings.redis_url:
        log.warning(
            "SECURITY: no WEAVE_REDIS_URL, so rate limits are per-process. With N "
            "uvicorn workers the effective limit is N times the configured one. "
            "Point WEAVE_REDIS_URL at a Redis instance before running more than "
            "one worker."
        )

    if problems:
        raise RuntimeError(
            "Refusing to start with insecure production settings:\n  - "
            + "\n  - ".join(problems)
        )

    # Loud, but not fatal: these are deliberate choices with real consequences
    # if the instance is reachable from the internet.
    if settings.workspace_enabled and settings.workspace_network:
        log.warning(
            "SECURITY: the developer workspace can execute code with network access. "
            "Every VERIFIED user of this instance can run commands in a container on "
            "this host. Set WEAVE_WORKSPACE_ENABLED=false before exposing Weave to "
            "people you do not trust."
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _preflight()
    init_db()
    engine = get_engine()
    _artifact_sweeper()
    log.info("Weave gateway ready [env=%s, llm=%s, sandbox=%s, workspace=%s]",
             settings.environment, getattr(engine, "name", "offline"),
             settings.sandbox_backend,
             "on" if settings.workspace_enabled else "off")
    yield


app = FastAPI(
    title="Weave API",
    version="1.0.0",
    description="Bilingual (Kiswahili/English) study + research platform for Tanzania.",
    docs_url="/docs",
    openapi_url=f"{settings.api_prefix}/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)

app.include_router(api_router, prefix=settings.api_prefix)

from .telemetry import setup_telemetry  # noqa: E402
setup_telemetry(app)


@app.get("/health")
def health() -> JSONResponse:
    engine = get_engine()
    from .services.retrieval.embeddings import embedding_backend
    from .services.tools import get_registry
    from .services.warehouse import get_warehouse
    from .services.websearch import get_web_search
    return JSONResponse({
        "status": "ok",
        "environment": settings.environment,
        "llm_engine": getattr(engine, "name", "offline"),
        "embedding_backend": embedding_backend(),
        "sandbox_backend": settings.sandbox_backend,
        "database": "sqlite" if settings.is_sqlite else "postgres",
        "tools": sorted(t.name for t in get_registry().all()),
        "capabilities": {
            "web_search": get_web_search().enabled,
            "browserless": bool(settings.browserless_url),
            "render_service": bool(settings.render_service_url),
            "gotenberg": bool(settings.gotenberg_url),
            "warehouse": get_warehouse().enabled,
            "clickhouse": bool(settings.clickhouse_url),
        },
    })


@app.get("/")
def root() -> dict:
    return {"name": "Weave API", "version": "1.0.0", "docs": "/docs",
            "api_prefix": settings.api_prefix}
