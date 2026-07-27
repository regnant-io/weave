"""Background jobs (architecture §2: Celery workers, Redis broker).

Designed to degrade gracefully: when Redis isn't configured (the zero-service dev
boot), `dispatch()` runs the job inline in a thread instead of enqueuing it, so
the same call site works with or without a worker. With Redis + a running worker
(`--profile full`), jobs run out-of-process.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from .config import settings

log = logging.getLogger("weave.tasks")

_celery = None


def get_celery():
    """Lazily build the Celery app when Redis is configured."""
    global _celery
    if _celery is not None:
        return _celery
    if not settings.redis_url:
        return None
    try:
        from celery import Celery
        _celery = Celery("weave", broker=settings.redis_url, backend=settings.redis_url)
        _celery.conf.update(task_serializer="json", accept_content=["json"],
                            result_serializer="json", timezone="UTC",
                            task_always_eager=settings.celery_always_eager)
    except Exception:  # noqa: BLE001
        _celery = None
    return _celery


# --- job registry ----------------------------------------------------------
_JOBS: dict[str, Callable[..., Any]] = {}


def job(name: str):
    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        _JOBS[name] = fn
        cel = get_celery()
        if cel is not None:
            cel.task(name=name)(fn)
        return fn
    return deco


def dispatch(name: str, *args, **kwargs) -> str:
    """Enqueue a job (Redis) or run it inline in a daemon thread (no Redis)."""
    cel = get_celery()
    if cel is not None and not settings.celery_always_eager:
        try:
            res = cel.send_task(name, args=list(args), kwargs=kwargs)
            return f"queued:{res.id}"
        except Exception:  # noqa: BLE001 - broker down -> inline
            pass
    fn = _JOBS.get(name)
    if fn is None:
        return "unknown-job"
    threading.Thread(target=lambda: _safe(fn, *args, **kwargs), daemon=True).start()
    return "inline"


def _safe(fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        log.warning("job failed: %s", exc)


# --- jobs -------------------------------------------------------------------
@job("weave.ingest_source")
def ingest_source_job(source_id: str) -> None:
    from .db import SessionLocal
    from .models import Source
    from .services.ingestion import get_ingestion
    db = SessionLocal()
    try:
        src = db.query(Source).filter(Source.id == source_id).first()
        if src:
            get_ingestion().ingest(db, src)
    finally:
        db.close()


@job("weave.resummarize_project")
def resummarize_project_job(project_id: str) -> None:
    from .db import SessionLocal
    from .models import Project
    from .services.orchestration import get_orchestrator
    db = SessionLocal()
    try:
        p = db.query(Project).filter(Project.id == project_id).first()
        if p:
            get_orchestrator().resummarize_project(db, p)
    finally:
        db.close()


# Module-level Celery app for the worker entrypoint (`celery -A app.tasks worker`).
# None when Redis isn't configured (the worker service only runs under --profile full).
celery = get_celery()
