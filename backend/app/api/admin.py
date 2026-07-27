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
from ..models import (AnalysisRun, Dataset, Message, Project, SandboxAudit, Source,
                      SourceChunk, User)
from ..tasks import dispatch

router = APIRouter()


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
