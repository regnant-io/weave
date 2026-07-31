"""Admin / ops dashboard API (architecture 4.2 /admin, §7.4 ingestion, §8.4 audit).

Gated to admin/institutional users. Surfaces the operational data the platform
already records (sandbox audit log, source library / ingestion status) and lets
an operator trigger ingestion.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_admin_user
from ..models import (AnalysisRun, CrawlPage, CrawlSeed, Dataset, Message, Project,
                      SandboxAudit, Source, SourceChunk, User)
from ..tasks import dispatch

router = APIRouter()


def _seed_out(db: Session, s: CrawlSeed) -> dict:
    pages = db.query(func.count()).select_from(CrawlPage).filter(
        CrawlPage.seed_id == s.id).scalar() or 0
    return {
        "id": s.id, "url": s.url, "domain": s.domain, "source_type": s.source_type,
        "language": s.language, "origin": s.origin, "enabled": s.enabled,
        "max_depth": s.max_depth, "max_pages": s.max_pages,
        "delay_seconds": s.delay_seconds, "same_domain_only": s.same_domain_only,
        "render_js": s.render_js, "status": s.status, "last_error": s.last_error,
        "pages_fetched": s.pages_fetched, "pages_indexed": s.pages_indexed,
        "pages_recorded": int(pages),
        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


@router.get("/stats")
def stats(db: Session = Depends(get_db), _admin: User = Depends(get_admin_user)) -> dict:
    def count(model) -> int:
        return db.query(func.count()).select_from(model).scalar() or 0
    return {
        "users": count(User), "projects": count(Project), "datasets": count(Dataset),
        "messages": count(Message), "sources": count(Source), "chunks": count(SourceChunk),
        "analysis_runs": count(AnalysisRun), "sandbox_audits": count(SandboxAudit),
    }


@router.get("/audit")
def audit(limit: int = 50, db: Session = Depends(get_db), _admin: User = Depends(get_admin_user)):
    rows = db.query(SandboxAudit).order_by(SandboxAudit.created_at.desc()).limit(min(limit, 200)).all()
    return [{
        "id": r.id, "user_id": r.user_id, "dataset_id": r.dataset_id, "status": r.status,
        "code_hash": r.code_hash[:12], "execution_time_ms": r.execution_time_ms,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]


@router.get("/sources")
def sources(db: Session = Depends(get_db), _admin: User = Depends(get_admin_user)):
    rows = db.query(Source).order_by(Source.ingested_at.desc()).all()
    out = []
    for s in rows:
        chunks = db.query(func.count()).select_from(SourceChunk).filter(
            SourceChunk.source_id == s.id).scalar() or 0
        out.append({"id": s.id, "title": s.title, "url": s.url, "source_type": s.source_type,
                    "access_status": s.access_status, "predatory_flag": s.predatory_flag,
                    "chunks": chunks,
                    "ingested_at": s.ingested_at.isoformat() if s.ingested_at else None})
    return out


@router.post("/ingest")
def trigger_ingest(body: dict, db: Session = Depends(get_db), _admin: User = Depends(get_admin_user)):
    """Ingest a URL now (creates the Source + chunks) or re-ingest an existing source."""
    from ..services.ingestion import get_ingestion
    if body.get("source_id"):
        job = dispatch("weave.ingest_source", body["source_id"])
        return {"queued": job, "source_id": body["source_id"]}
    url = body.get("url")
    if not url:
        return {"error": "provide url or source_id"}
    src = get_ingestion().ingest_url(
        db, url, source_type=body.get("source_type", "gov"),
        access_status=body.get("access_status", "open"), language=body.get("language", "en"),
        title=body.get("title"),
    )
    chunks = db.query(func.count()).select_from(SourceChunk).filter(
        SourceChunk.source_id == src.id).scalar() or 0
    return {"ingested": True, "source_id": src.id, "title": src.title, "chunks": chunks}


# --- crawler -----------------------------------------------------------------
# The crawler is how the library grows. Everything here is an operator action:
# seeds are created or approved by a human, and a crawl only ever starts because
# someone (or the scheduled worker) asked for it. See services/crawler for the
# politeness rules that make this safe to point at a ministry's web server.

@router.get("/crawl/seeds")
def list_seeds(origin: str = "", db: Session = Depends(get_db),
               _admin: User = Depends(get_admin_user)):
    q = db.query(CrawlSeed)
    if origin in {"admin", "session"}:
        q = q.filter(CrawlSeed.origin == origin)
    rows = q.order_by(CrawlSeed.created_at.desc()).limit(300).all()
    return [_seed_out(db, s) for s in rows]


@router.post("/crawl/seeds")
def create_seed(body: dict, db: Session = Depends(get_db),
                _admin: User = Depends(get_admin_user)):
    from urllib.parse import urlparse
    url = (body.get("url") or "").strip()
    if not url:
        return {"error": "url is required"}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    domain = urlparse(url).netloc.lower()
    if not domain:
        return {"error": "could not read a domain from that url"}

    existing = db.query(CrawlSeed).filter(CrawlSeed.domain == domain).first()
    if existing:
        return {"error": f"a seed for {domain} already exists", "seed": _seed_out(db, existing)}

    seed = CrawlSeed(
        url=url, domain=domain,
        source_type=body.get("source_type", "gov"),
        language=body.get("language", "en"),
        origin="admin", enabled=True,
        max_depth=int(body.get("max_depth", 2)),
        max_pages=int(body.get("max_pages", 40)),
        delay_seconds=float(body.get("delay_seconds", 1.0)),
        same_domain_only=bool(body.get("same_domain_only", True)),
        render_js=bool(body.get("render_js", False)),
    )
    db.add(seed)
    db.commit()
    db.refresh(seed)
    return {"created": True, "seed": _seed_out(db, seed)}


@router.patch("/crawl/seeds/{seed_id}")
def update_seed(seed_id: str, body: dict, db: Session = Depends(get_db),
                _admin: User = Depends(get_admin_user)):
    """Edit a seed's budget, or approve a session-discovered one by enabling it."""
    seed = db.get(CrawlSeed, seed_id)
    if seed is None:
        return {"error": "seed not found"}
    for field, cast in (
        ("enabled", bool), ("same_domain_only", bool), ("render_js", bool),
        ("max_depth", int), ("max_pages", int), ("delay_seconds", float),
        ("source_type", str), ("language", str),
    ):
        if field in body:
            setattr(seed, field, cast(body[field]))
    db.add(seed)
    db.commit()
    db.refresh(seed)
    return {"updated": True, "seed": _seed_out(db, seed)}


@router.delete("/crawl/seeds/{seed_id}")
def delete_seed(seed_id: str, db: Session = Depends(get_db),
                _admin: User = Depends(get_admin_user)):
    seed = db.get(CrawlSeed, seed_id)
    if seed is None:
        return {"error": "seed not found"}
    db.query(CrawlPage).filter(CrawlPage.seed_id == seed_id).delete()
    db.delete(seed)
    db.commit()
    return {"deleted": True}


@router.post("/crawl/seeds/{seed_id}/run")
def run_seed(seed_id: str, db: Session = Depends(get_db),
             _admin: User = Depends(get_admin_user)):
    """Start a crawl.

    Always asynchronous — `dispatch` sends it to the Celery worker when Redis is
    configured and to a daemon thread otherwise. A polite crawl is mostly time
    spent deliberately waiting between requests, so it must never hold an API
    request open. Poll the seed row for progress.
    """
    seed = db.get(CrawlSeed, seed_id)
    if seed is None:
        return {"error": "seed not found"}
    if not seed.enabled:
        return {"error": "this seed is disabled — enable it first"}
    if seed.status == "running":
        return {"error": "this seed is already crawling"}

    seed.status = "running"
    seed.last_error = ""
    db.add(seed)
    db.commit()
    handle = dispatch("weave.crawl_seed", seed_id)
    return {"started": True, "mode": handle, "seed_id": seed_id,
            "seed": _seed_out(db, seed)}


@router.get("/crawl/seeds/{seed_id}/pages")
def seed_pages(seed_id: str, status: str = "", limit: int = 100,
               db: Session = Depends(get_db), _admin: User = Depends(get_admin_user)):
    """Every URL this seed considered and what became of it.

    Refusals are included on purpose: "why is this page not in the library" is
    the question an operator actually has, and it is unanswerable if only
    successes were recorded.
    """
    q = db.query(CrawlPage).filter(CrawlPage.seed_id == seed_id)
    if status:
        q = q.filter(CrawlPage.status == status)
    rows = q.order_by(CrawlPage.created_at.desc()).limit(min(limit, 500)).all()
    return [{
        "id": p.id, "url": p.url, "depth": p.depth, "status": p.status,
        "reason": p.reason, "title": p.title, "chars": p.chars,
        "source_id": p.source_id,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    } for p in rows]


@router.delete("/sources/{source_id}")
def delete_source(source_id: str, db: Session = Depends(get_db),
                  _admin: User = Depends(get_admin_user)):
    """Remove a source and its chunks — the operator's undo for a bad crawl."""
    src = db.get(Source, source_id)
    if src is None:
        return {"error": "source not found"}
    db.query(SourceChunk).filter(SourceChunk.source_id == source_id).delete()
    db.delete(src)
    db.commit()
    return {"deleted": True}
