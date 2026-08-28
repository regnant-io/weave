"""Project routes — the persistent research workspace (architecture 4.2 / 9)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Message, Project, User
from ..schemas import (HypothesisIn, MessageOut, ProjectCreate, ProjectOut,
                       ProjectUpdate)

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


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(project_id: str, body: ProjectUpdate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """Rename a project or switch its mode."""
    project = _get_owned_project(db, project_id, user)
    if body.title is not None:
        title = body.title.strip()[:255]
        if not title:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "title cannot be empty")
        project.title = title
    if body.mode in {"student", "researcher"}:
        project.mode = body.mode
    db.add(project)
    db.commit()
    db.refresh(project)
    return ProjectOut.model_validate(project)


@router.delete("/{project_id}")
def delete_project(project_id: str, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """Delete a project and everything under it.

    Threads, messages, datasets, citations and memory all cascade from the ORM
    relationships. The on-disk workspace is removed separately because it lives
    outside the database.
    """
    project = _get_owned_project(db, project_id, user)
    _purge_workspace(project.id)
    db.delete(project)
    db.commit()
    return {"deleted": True, "id": project_id}


@router.delete("")
def delete_all_projects(confirm: str = "", db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """Delete EVERY project for the caller.

    Requires `?confirm=DELETE`. The UI already shows a confirmation modal, but a
    destructive bulk endpoint should not be reachable by a bare DELETE that a
    mistyped URL or a stray client retry could trigger.
    """
    if confirm != "DELETE":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "pass ?confirm=DELETE to delete every project",
        )
    projects = db.query(Project).filter(Project.user_id == user.id).all()
    for p in projects:
        _purge_workspace(p.id)
        db.delete(p)
    db.commit()
    return {"deleted": len(projects)}


def _purge_workspace(project_id: str) -> None:
    """Remove a project's on-disk developer workspace.

    Best effort: a locked file on Windows must not prevent the database rows
    from being deleted, or the user is left with a project they cannot remove.
    """
    try:
        import shutil
        from ..services.workspace import get_workspace_service
        target = get_workspace_service().project_dir(project_id)
        shutil.rmtree(target, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass


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
