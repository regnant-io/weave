"""Dataset routes (architecture 5.2): multipart upload -> object storage,
Dataset row, profiling. Idempotency keys supported (mobile connections retry)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Dataset, Project, User
from ..schemas import DatasetOut
from ..services.analysis import get_analysis_service
from ..storage import storage

router = APIRouter()

ALLOWED_EXT = {".csv", ".tsv", ".xlsx", ".xls", ".json"}
MAX_STUDENT_BYTES = 5 * 1024 * 1024
MAX_RESEARCHER_BYTES = 100 * 1024 * 1024

# in-memory idempotency cache (Redis in production)
_idempotency: dict[str, str] = {}


@router.post("/projects/{project_id}/datasets", response_model=DatasetOut, status_code=201)
async def upload_dataset(
    project_id: str,
    file: UploadFile,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None),
) -> DatasetOut:
    project = db.query(Project).filter(
        Project.id == project_id, Project.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")

    if idempotency_key and idempotency_key in _idempotency:
        existing = db.query(Dataset).filter(Dataset.id == _idempotency[idempotency_key]).first()
        if existing:
            return DatasetOut.model_validate(existing)

    filename = file.filename or "upload.csv"
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in ALLOWED_EXT:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unsupported file type {ext!r}")

    data = await file.read()
    limit = MAX_RESEARCHER_BYTES if project.mode == "researcher" else MAX_STUDENT_BYTES
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"file exceeds {limit // (1024*1024)}MB limit for {project.mode} mode")

    dataset = Dataset(
        project_id=project.id, original_filename=filename, size_bytes=len(data),
        s3_key="", status="profiling",
    )
    db.add(dataset)
    db.flush()
    key = f"datasets/{project.id}/{dataset.id}{ext}"
    storage.put_bytes(key, data)
    dataset.s3_key = key
    db.commit()
    db.refresh(dataset)

    # Profiling: architecture 3 queues this on Celery; we run it inline for a
    # zero-service boot. Swap to a Celery task with the same call for scale.
    get_analysis_service().profile(dataset, db)
    db.refresh(dataset)

    if idempotency_key:
        _idempotency[idempotency_key] = dataset.id
    return DatasetOut.model_validate(dataset)


@router.get("/projects/{project_id}/datasets", response_model=list[DatasetOut])
def list_project_datasets(
    project_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(
        Project.id == project_id, Project.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    datasets = db.query(Dataset).filter(Dataset.project_id == project_id).order_by(
        Dataset.uploaded_at.desc()
    ).all()
    return [DatasetOut.model_validate(d) for d in datasets]


@router.get("/datasets/{dataset_id}/profile", response_model=DatasetOut)
def dataset_profile(dataset_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    dataset = (
        db.query(Dataset).join(Project).filter(
            Dataset.id == dataset_id, Project.user_id == user.id
        ).first()
    )
    if not dataset:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dataset not found")
    return DatasetOut.model_validate(dataset)
