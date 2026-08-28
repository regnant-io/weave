"""Read-only views over a project's developer workspace, plus a reset.

The assistant drives the workspace through tools; these endpoints exist so the
UI can show what was built (a file tree, a file's contents, how large it has
grown) and so the user can start over. Nothing here executes code — that path
stays behind the tool layer and the container.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Project, User
from ..services.workspace import get_workspace_service

router = APIRouter()


def _owned(db: Session, project_id: str, user: User) -> Project:
    project = db.query(Project).filter(
        Project.id == project_id, Project.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return project


@router.get("/projects/{project_id}/workspace")
def workspace_tree(project_id: str, path: str = "", depth: int = 4,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _owned(db, project_id, user)
    svc = get_workspace_service()
    tree = svc.list_tree(project_id, path, depth)
    return {**tree, "enabled": svc.enabled, "stats": svc.stats(project_id)}


@router.get("/projects/{project_id}/workspace/file")
def workspace_file(project_id: str, path: str, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    _owned(db, project_id, user)
    result = get_workspace_service().read_file(project_id, path)
    if result.get("status") != "ok":
        raise HTTPException(status.HTTP_404_NOT_FOUND, result.get("error", "not found"))
    return result


@router.delete("/projects/{project_id}/workspace")
def reset_workspace(project_id: str, confirm: str = "", db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """Wipe the workspace. Requires ?confirm=RESET — it destroys real work."""
    _owned(db, project_id, user)
    if confirm != "RESET":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "pass ?confirm=RESET to erase this workspace")
    return get_workspace_service().reset(project_id)


@router.get("/workspace/status")
def workspace_status(_user: User = Depends(get_current_user)) -> dict:
    """Whether execution is actually available, for the settings page.

    Re-probes rather than trusting the cached answer, so starting Docker and
    hitting refresh is enough to bring the capability online without a restart.
    """
    from ..config import settings
    svc = get_workspace_service()
    return {
        "enabled": svc.refresh(),
        "image": settings.workspace_image,
        "network": settings.workspace_network,
        "memory_mb": settings.workspace_memory_mb,
        "cpus": settings.workspace_cpus,
        "default_timeout": settings.workspace_exec_timeout,
    }
