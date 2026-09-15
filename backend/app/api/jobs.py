"""User-visible state for durable background work."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import JobRecord, User

router = APIRouter()


def _out(row: JobRecord) -> dict:
    return {
        "id": row.id, "kind": row.kind, "project_id": row.project_id,
        "status": row.status, "progress": row.progress, "attempts": row.attempts,
        "error": row.error if row.status in {"retrying", "failed", "dead_letter"} else "",
        "created_at": row.created_at, "updated_at": row.updated_at,
    }


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)) -> dict:
    row = db.get(JobRecord, job_id)
    if row is None or (row.owner_id and row.owner_id != user.id and user.role != "admin"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return _out(row)


@router.get("/jobs")
def list_jobs(limit: int = 50, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)) -> list[dict]:
    rows = (db.query(JobRecord).filter(JobRecord.owner_id == user.id)
            .order_by(JobRecord.created_at.desc()).limit(min(max(limit, 1), 200)).all())
    return [_out(row) for row in rows]
