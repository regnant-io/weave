"""Analysis route (architecture 5.2: POST /analysis/run).

Internal-facing in the architecture (called by Orchestration), but also exposed
directly so a dataset view can run explicit, user-authored analysis. Rate-limited
on the stricter sandbox bucket (architecture 5.3 / 8)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import enforce_sandbox_limit
from ..models import Dataset, Project, User
from ..schemas import AnalysisRunOut, AnalysisRunRequest
from ..services.analysis import get_analysis_service

router = APIRouter()


@router.post("/run", response_model=AnalysisRunOut)
def run_analysis(
    body: AnalysisRunRequest,
    db: Session = Depends(get_db),
    user: User = Depends(enforce_sandbox_limit),
) -> AnalysisRunOut:
    dataset = (
        db.query(Dataset).join(Project).filter(
            Dataset.id == body.dataset_id, Project.user_id == user.id
        ).first()
    )
    if not dataset:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dataset not found")

    heavy = body.heavy and user.trust_tier == "institutional"  # heavy jobs gated by tier
    run = get_analysis_service().run_code(
        db, code=body.code, dataset=dataset, heavy=heavy, user_id=user.id,
    )
    return AnalysisRunOut.model_validate(run)
