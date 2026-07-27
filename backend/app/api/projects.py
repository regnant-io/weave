"""Project routes — the persistent research workspace (architecture 4.2 / 9)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Message, Project, User
from ..schemas import HypothesisIn, MessageOut, ProjectCreate, ProjectOut

router = APIRouter()


def _get_owned_project(db: Session, project_id: str, user: User) -> Project:
    project = db.query(Project).filter(
        Project.id == project_id, Project.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return project


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    body: ProjectCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user),
) -> ProjectOut:
    project = Project(user_id=user.id, title=body.title, mode=body.mode, hypotheses=[], summary="")
    db.add(project)
    db.commit()
    db.refresh(project)
    return ProjectOut.model_validate(project)


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    projects = db.query(Project).filter(Project.user_id == user.id).order_by(
        Project.created_at.desc()
    ).all()
    return [ProjectOut.model_validate(p) for p in projects]


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return ProjectOut.model_validate(_get_owned_project(db, project_id, user))


@router.get("/{project_id}/messages", response_model=list[MessageOut])
def get_messages(project_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _get_owned_project(db, project_id, user)
    msgs = db.query(Message).filter(Message.project_id == project_id).order_by(
        Message.created_at
    ).all()
    return [MessageOut.model_validate(m) for m in msgs]


@router.post("/{project_id}/hypotheses", response_model=ProjectOut)
def add_hypothesis(
    project_id: str, body: HypothesisIn,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    import uuid
    from datetime import datetime, timezone
    project = _get_owned_project(db, project_id, user)
    hyps = list(project.hypotheses or [])
    hyps.append({
        "id": uuid.uuid4().hex[:8], "text_sw": body.text_sw, "text_en": body.text_en,
        "status": body.status, "created_at": datetime.now(timezone.utc).isoformat(),
    })
    project.hypotheses = hyps
    db.add(project)
    db.commit()
    db.refresh(project)
    return ProjectOut.model_validate(project)


@router.patch("/{project_id}/hypotheses/{hyp_id}", response_model=ProjectOut)
def update_hypothesis(project_id: str, hyp_id: str, body: dict,
                      db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = _get_owned_project(db, project_id, user)
    hyps = list(project.hypotheses or [])
    for h in hyps:
        if h.get("id") == hyp_id:
            if body.get("status") in {"open", "supported", "refuted"}:
                h["status"] = body["status"]
            for k in ("text_sw", "text_en"):
                if isinstance(body.get(k), str):
                    h[k] = body[k]
    project.hypotheses = hyps
    db.add(project); db.commit(); db.refresh(project)
    return ProjectOut.model_validate(project)


@router.delete("/{project_id}/hypotheses/{hyp_id}", response_model=ProjectOut)
def delete_hypothesis(project_id: str, hyp_id: str,
                      db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = _get_owned_project(db, project_id, user)
    project.hypotheses = [h for h in (project.hypotheses or []) if h.get("id") != hyp_id]
    db.add(project); db.commit(); db.refresh(project)
    return ProjectOut.model_validate(project)


@router.post("/{project_id}/notes", response_model=ProjectOut)
def add_note(project_id: str, body: dict,
             db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    import uuid
    from datetime import datetime, timezone
    project = _get_owned_project(db, project_id, user)
    notes = list(project.notes or [])
    notes.append({"id": uuid.uuid4().hex[:8], "text": str(body.get("text", ""))[:2000],
                  "created_at": datetime.now(timezone.utc).isoformat()})
    project.notes = notes
    db.add(project); db.commit(); db.refresh(project)
    return ProjectOut.model_validate(project)


@router.post("/{project_id}/summarize", response_model=ProjectOut)
def resummarize(project_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Regenerate the project's rolling summary from its messages via the LLM."""
    from ..services.orchestration.orchestrator import get_orchestrator
    project = _get_owned_project(db, project_id, user)
    get_orchestrator().resummarize_project(db, project)
    db.refresh(project)
    return ProjectOut.model_validate(project)
