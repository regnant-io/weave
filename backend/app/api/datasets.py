"""Dataset routes (architecture 5.2): multipart upload -> object storage,
Dataset row, profiling. Idempotency keys supported (mobile connections retry)."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import Dataset, IdempotencyRecord, Project, User
from ..schemas import DatasetOut
from ..services.analysis import get_analysis_service
from ..storage import storage

router = APIRouter()

ALLOWED_EXT = {".csv", ".tsv", ".xlsx", ".xls", ".json"}
MAX_STUDENT_BYTES = 5 * 1024 * 1024
MAX_RESEARCHER_BYTES = 100 * 1024 * 1024

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

    if idempotency_key and len(idempotency_key) > 128:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Idempotency-Key may contain at most 128 characters")

    filename = file.filename or "upload.csv"
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in ALLOWED_EXT:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unsupported file type {ext!r}")

    limit = MAX_RESEARCHER_BYTES if project.mode == "researcher" else MAX_STUDENT_BYTES
    # Starlette's UploadFile is already a spooled file.  Measure and stream that
    # file into storage instead of allocating a second 100 MB bytes object, and
    # reject it before copying when it exceeds the role limit.
    await file.seek(0)
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"file exceeds {limit // (1024*1024)}MB limit for {project.mode} mode")

    digest = hashlib.sha256()
    digest.update(filename.encode("utf-8", "replace"))
    while chunk := file.file.read(1024 * 1024):
        digest.update(chunk)
    request_hash = digest.hexdigest()
    file.file.seek(0)

    record = None
    dataset = None
    if idempotency_key:
        record = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.namespace == "dataset_upload",
            IdempotencyRecord.owner_id == user.id,
            IdempotencyRecord.project_id == project.id,
            IdempotencyRecord.key == idempotency_key,
        ).first()
        if record:
            expiry = record.expires_at
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry <= datetime.now(timezone.utc):
                db.delete(record)
                db.commit()
                record = None
            elif record.request_hash != request_hash:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "Idempotency-Key was already used for a different upload",
                )
            else:
                dataset = db.query(Dataset).filter(
                    Dataset.id == record.resource_id,
                    Dataset.project_id == project.id,
                ).first()
                if dataset and dataset.status == "ready" and storage.exists(dataset.s3_key):
                    dataset.job_id = (record.response or {}).get("job_id")
                    return DatasetOut.model_validate(dataset)

    if dataset is None:
        dataset = Dataset(
            project_id=project.id, original_filename=filename, size_bytes=size,
            s3_key="", status="profiling",
        )
        db.add(dataset)
        db.flush()
        if record is not None:
            record.resource_id = dataset.id
    key = dataset.s3_key or f"datasets/{project.id}/{dataset.id}{ext}"
    dataset.s3_key = key
    if idempotency_key and record is None:
        record = IdempotencyRecord(
            namespace="dataset_upload", owner_id=user.id, project_id=project.id,
            key=idempotency_key, request_hash=request_hash,
            resource_type="dataset", resource_id=dataset.id,
            expires_at=datetime.now(timezone.utc) + timedelta(
                seconds=settings.idempotency_ttl_seconds
            ),
        )
        db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if not idempotency_key:
            raise
        winner = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.namespace == "dataset_upload",
            IdempotencyRecord.owner_id == user.id,
            IdempotencyRecord.project_id == project.id,
            IdempotencyRecord.key == idempotency_key,
        ).first()
        if winner is None or winner.request_hash != request_hash:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Idempotency-Key is already in use")
        dataset = db.query(Dataset).filter(Dataset.id == winner.resource_id).first()
        if dataset is None:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "idempotent upload is still being created")
        record = winner
        key = dataset.s3_key

    storage.put_stream(key, file.file)
    db.refresh(dataset)

    job_id = None
    if settings.redis_url and not settings.celery_always_eager:
        from ..tasks import dispatch
        job_id = dispatch("weave.profile_dataset", dataset.id,
                          job_owner_id=user.id, job_project_id=project.id)
        dataset.job_id = job_id
    else:
        # The zero-service developer path stays deterministic and immediately
        # useful; deployed multi-worker paths always leave profiling to a worker.
        get_analysis_service().profile(dataset, db)
        db.refresh(dataset)

    if record:
        record.response = {"dataset_id": dataset.id, "status": dataset.status,
                           **({"job_id": job_id} if job_id else {})}
        db.add(record)
        db.commit()
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
