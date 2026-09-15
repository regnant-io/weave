"""Background jobs (architecture §2: Celery workers, Redis broker).

Designed to degrade gracefully: when Redis isn't configured (the zero-service dev
boot), `dispatch()` runs the job inline in a thread instead of enqueuing it, so
the same call site works with or without a worker. With Redis + a running worker
(`--profile full`), jobs run out-of-process.
"""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
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
        def tracked(*args, _job_id: str | None = None, **kwargs):
            if _job_id:
                _set_job(_job_id, "running", increment_attempt=True)
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                if _job_id:
                    _set_job(_job_id, "failed", error=str(exc)[:2000])
                raise
            if _job_id:
                progress = result if isinstance(result, dict) else {"completed": True}
                _set_job(_job_id, "succeeded", progress=progress)
            return result

        tracked.__name__ = fn.__name__
        tracked.__doc__ = fn.__doc__
        _JOBS[name] = tracked
        cel = get_celery()
        if cel is not None:
            # Application failures retry with bounded exponential backoff.
            # Exhausting that budget leaves a durable dead-letter record.
            def celery_tracked(task, *args, **kwargs):
                try:
                    return tracked(*args, **kwargs)
                except Exception as exc:
                    job_id = kwargs.get("_job_id")
                    retries = int(getattr(task.request, "retries", 0))
                    if retries < settings.job_max_retries:
                        delay = min(
                            settings.job_retry_base_seconds * (2 ** retries),
                            15 * 60,
                        )
                        if job_id:
                            _set_job(job_id, "retrying", error=str(exc)[:2000])
                        raise task.retry(exc=exc, countdown=delay)
                    if job_id:
                        _set_job(job_id, "dead_letter", error=str(exc)[:2000])
                    raise

            celery_tracked.__name__ = f"{fn.__name__}_celery"
            cel.task(name=name, bind=True, acks_late=True,
                     reject_on_worker_lost=True)(celery_tracked)
        return tracked
    return deco


def _new_job(name: str, owner_id: str = "", project_id: str = "") -> str:
    from .db import SessionLocal
    from .models import JobRecord
    db = SessionLocal()
    try:
        row = JobRecord(id=uuid.uuid4().hex, kind=name, owner_id=owner_id,
                        project_id=project_id, status="queued")
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def _set_job(job_id: str, state: str, *, progress: dict | None = None,
             error: str = "", increment_attempt: bool = False,
             celery_task_id: str = "") -> None:
    from .db import SessionLocal
    from .models import JobRecord
    db = SessionLocal()
    metric: tuple[str, str, float] | None = None
    try:
        row = db.get(JobRecord, job_id)
        if row is None:
            return
        now = datetime.now(timezone.utc)
        previous_update = row.updated_at
        if previous_update and previous_update.tzinfo is None:
            previous_update = previous_update.replace(tzinfo=timezone.utc)
        created = row.created_at
        if created and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if state == "running" and created:
            metric = (row.kind, "queue", max(0.0, (now - created).total_seconds() * 1000))
        elif state in {"succeeded", "failed", "dead_letter"} and previous_update:
            metric = (row.kind, state,
                      max(0.0, (now - previous_update).total_seconds() * 1000))
        row.status = state
        row.updated_at = now
        if progress is not None:
            row.progress = progress
        if error:
            row.error = error
        elif state == "succeeded":
            row.error = ""
        if increment_attempt:
            row.attempts = (row.attempts or 0) + 1
        if celery_task_id:
            row.celery_task_id = celery_task_id
        db.add(row)
        db.commit()
    finally:
        db.close()
    if metric:
        from .metrics import observe
        observe("job", metric[0], metric[1], metric[2])


def dispatch(name: str, *args, job_owner_id: str = "", job_project_id: str = "",
             **kwargs) -> str:
    """Enqueue a tracked job and return its durable job-record id."""
    if name not in _JOBS:
        return "unknown-job"
    job_id = _new_job(name, job_owner_id, job_project_id)
    cel = get_celery()
    if cel is not None and not settings.celery_always_eager:
        try:
            res = cel.send_task(name, args=list(args), kwargs={**kwargs, "_job_id": job_id})
            _set_job(job_id, "queued", celery_task_id=res.id)
            return job_id
        except Exception as exc:  # noqa: BLE001 - broker outage is visible
            if settings.is_deployed:
                _set_job(job_id, "failed", error=f"broker unavailable: {exc}"[:2000])
                return job_id
    fn = _JOBS.get(name)
    threading.Thread(target=lambda: _safe(fn, *args, _job_id=job_id, **kwargs),
                     daemon=True).start()
    return job_id


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


@job("weave.crawl_seed")
def crawl_seed_job(seed_id: str) -> None:
    """Run one crawl seed to its budget.

    Always a background job: a polite crawl is mostly time spent deliberately
    waiting between requests, so it must never hold an API request open.
    """
    from .db import SessionLocal
    from .models import CrawlSeed
    from .services.crawler import get_crawler
    db = SessionLocal()
    try:
        seed = db.query(CrawlSeed).filter(CrawlSeed.id == seed_id).first()
        if seed is None:
            return
        if not seed.enabled:
            log.info("crawl seed %s is disabled; not running", seed_id)
            return
        stats = get_crawler().run_seed(db, seed)
        log.info("crawled %s: %d fetched, %d indexed, %d skipped, %d errors (%s)",
                 seed.domain, stats.fetched, stats.indexed, stats.skipped,
                 stats.errors, stats.stopped_because)
    except Exception as exc:  # noqa: BLE001 - never let a crawl kill the worker
        log.warning("crawl seed %s failed: %s", seed_id, exc)
        try:
            seed = db.query(CrawlSeed).filter(CrawlSeed.id == seed_id).first()
            if seed is not None:
                seed.status = "error"
                seed.last_error = str(exc)[:500]
                db.add(seed)
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        # Let the job boundary retry this crawl instead of recording success.
        raise
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


@job("weave.profile_dataset")
def profile_dataset_job(dataset_id: str) -> dict:
    from .db import SessionLocal
    from .models import Dataset
    from .services.analysis import get_analysis_service
    db = SessionLocal()
    try:
        dataset = db.get(Dataset, dataset_id)
        if dataset is None:
            raise LookupError("dataset not found")
        get_analysis_service().profile(dataset, db)
        return {"dataset_id": dataset_id, "status": dataset.status}
    finally:
        db.close()


@job("weave.deliver_outbox")
def deliver_outbox_job(event_id: str) -> dict:
    from .db import SessionLocal
    from .models import OutboxEvent
    db = SessionLocal()
    try:
        event = db.get(OutboxEvent, event_id)
        if event is None:
            raise LookupError("outbox event not found")
        if event.status == "delivered":
            return {"event_id": event_id, "status": "already_delivered"}
        event.status = "delivering"
        event.attempts = (event.attempts or 0) + 1
        db.add(event)
        db.commit()
        try:
            if event.topic == "whatsapp.reply":
                from .api.channels import _send_whatsapp
                _send_whatsapp(str(event.payload["phone"]), str(event.payload["text"]))
            else:
                raise ValueError(f"unsupported outbox topic {event.topic!r}")
        except Exception as exc:
            event.status = "failed"
            event.last_error = str(exc)[:2000]
            db.add(event)
            db.commit()
            raise
        event.status = "delivered"
        event.delivered_at = datetime.now(timezone.utc)
        event.last_error = ""
        db.add(event)
        db.commit()
        from .metrics import observe
        observe("channel", event.topic, "delivered")
        return {"event_id": event_id, "status": "delivered"}
    finally:
        db.close()


@job("weave.run_stream_turn")
def run_stream_turn_job(turn_id: str, project_id: str, user_id: str, user_text: str,
                        language: str, dataset_id: str | None, effort: str | None,
                        model: str | None, regenerate: bool,
                        services_pref: dict | None, thread_id: str | None,
                        channel: str, frames: list[str] | None) -> dict:
    """Durable producer for a streamed turn; events and cancel live in Redis."""
    from .db import SessionLocal
    from .models import Project
    from .services.orchestration import get_orchestrator
    from .services.orchestration.live import get_turns
    from .services.steering import get_steering

    live = get_turns().for_user(turn_id, user_id)
    if live is None:
        raise LookupError("durable turn metadata is missing")
    db = SessionLocal()
    error = ""
    msg = None
    meta: dict = {}
    try:
        project = db.query(Project).filter(
            Project.id == project_id, Project.user_id == user_id,
        ).first()
        if project is None:
            raise LookupError("project not found")
        msg, meta = get_orchestrator()._process(
            db, project, user_text, language, dataset_id, emit=live.emit,
            effort=effort, model=model, cancel=live.cancel, regenerate=regenerate,
            services_pref=services_pref, thread_id=thread_id, channel=channel,
            frames=frames, assistant_message_id=turn_id,
        )
    except Exception as exc:
        error = str(exc)
        raise
    finally:
        get_steering().finish(turn_id)
        db.close()
        if error:
            live.emit("error", {"message": error})
        else:
            live.emit("done", {
                "message_id": msg.id if msg else turn_id,
                "thread_id": meta.get("thread_id"),
                "next_thread_id": meta.get("next_thread_id"),
                "context_used": meta.get("context_used"),
                "context_window": meta.get("context_window"),
            })
        live.finish(error=error, result=meta)
    return {"turn_id": turn_id, "message_id": msg.id if msg else turn_id}


# Module-level Celery app for the worker entrypoint (`celery -A app.tasks worker`).
# None when Redis isn't configured (the worker service only runs under --profile full).
celery = get_celery()
