"""Threads (chats) inside a project, and the shared project memory they read.

A project is the durable workspace; a thread is one conversation in it. Keeping
them separate is what lets a user start a fresh chat without losing what earlier
chats established — continuity lives in project memory, not in one endless
message list.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import MemoryEntry, Message, Project, Thread, User
from ..schemas import (MemoryEntryIn, MemoryEntryOut, MessageOut, ThreadCreate,
                       ThreadOut, ThreadUpdate)
from ..services.memory import get_memory_service

router = APIRouter()


def _owned_project(db: Session, project_id: str, user: User) -> Project:
    project = db.query(Project).filter(
        Project.id == project_id, Project.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return project


def _owned_thread(db: Session, project: Project, thread_id: str) -> Thread:
    thread = db.query(Thread).filter(
        Thread.id == thread_id, Thread.project_id == project.id
    ).first()
    if not thread:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "thread not found")
    return thread


def _to_out(db: Session, t: Thread) -> ThreadOut:
    from sqlalchemy import func
    count = db.query(func.count(Message.id)).filter(Message.thread_id == t.id).scalar() or 0
    return ThreadOut(
        id=t.id, project_id=t.project_id, title=t.title or "Untitled",
        summary=t.summary or "", status=t.status,
        parent_thread_id=t.parent_thread_id, token_estimate=t.token_estimate or 0,
        message_count=int(count), created_at=t.created_at, updated_at=t.updated_at,
    )


@router.get("/projects/{project_id}/threads", response_model=list[ThreadOut])
def list_threads(project_id: str, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    project = _owned_project(db, project_id, user)
    memory = get_memory_service()
    # Guarantee at least one thread exists so the client never has to special-case
    # an empty project.
    if not db.query(Thread).filter(Thread.project_id == project.id).first():
        memory.active_thread(db, project)
        db.commit()
    rows = (
        db.query(Thread).filter(Thread.project_id == project.id)
        .order_by(Thread.updated_at.desc()).all()
    )
    return [_to_out(db, t) for t in rows]


@router.post("/projects/{project_id}/threads", response_model=ThreadOut, status_code=201)
def create_thread(project_id: str, body: ThreadCreate, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    project = _owned_project(db, project_id, user)
    thread = get_memory_service().create_thread(db, project, title=body.title or "")
    db.commit()
    db.refresh(thread)
    return _to_out(db, thread)


@router.get("/projects/{project_id}/threads/{thread_id}/messages",
            response_model=list[MessageOut])
def thread_messages(project_id: str, thread_id: str, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    project = _owned_project(db, project_id, user)
    _owned_thread(db, project, thread_id)
    rows = (
        db.query(Message).filter(Message.thread_id == thread_id)
        .order_by(Message.created_at).all()
    )
    return [MessageOut.model_validate(m) for m in rows]


@router.patch("/projects/{project_id}/threads/{thread_id}", response_model=ThreadOut)
def update_thread(project_id: str, thread_id: str, body: ThreadUpdate,
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = _owned_project(db, project_id, user)
    thread = _owned_thread(db, project, thread_id)
    if body.title is not None:
        thread.title = body.title.strip()[:255] or thread.title
    if body.status in {"active", "archived"}:
        thread.status = body.status
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return _to_out(db, thread)


@router.delete("/projects/{project_id}/threads/{thread_id}")
def delete_thread(project_id: str, thread_id: str, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    project = _owned_project(db, project_id, user)
    thread = _owned_thread(db, project, thread_id)
    db.delete(thread)
    db.commit()
    # A project must always have somewhere to type. Deleting the last thread
    # creates a fresh one rather than leaving a dead-end screen.
    memory = get_memory_service()
    if not db.query(Thread).filter(Thread.project_id == project.id).first():
        memory.active_thread(db, project)
        db.commit()
    return {"deleted": True}


@router.post("/projects/{project_id}/threads/{thread_id}/summarize", response_model=ThreadOut)
def summarize_thread(project_id: str, thread_id: str, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    from ..services.orchestration.llm import get_engine
    project = _owned_project(db, project_id, user)
    thread = _owned_thread(db, project, thread_id)
    get_memory_service().summarize_thread(db, thread, get_engine())
    db.commit()
    db.refresh(thread)
    return _to_out(db, thread)


# --- project memory --------------------------------------------------------

@router.get("/projects/{project_id}/memory", response_model=list[MemoryEntryOut])
def list_memory(project_id: str, q: str = "", db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    project = _owned_project(db, project_id, user)
    entries = get_memory_service().recall(db, project, q, limit=200)
    return [MemoryEntryOut.model_validate(e) for e in entries]


@router.post("/projects/{project_id}/memory", response_model=MemoryEntryOut)
def upsert_memory(project_id: str, body: MemoryEntryIn, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    project = _owned_project(db, project_id, user)
    entry = get_memory_service().remember(
        db, project, None, key=body.key, content=body.content,
        kind=body.kind, importance=body.importance,
    )
    db.commit()
    db.refresh(entry)
    return MemoryEntryOut.model_validate(entry)


@router.delete("/projects/{project_id}/memory/{key}")
def delete_memory(project_id: str, key: str, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    project = _owned_project(db, project_id, user)
    removed = get_memory_service().forget(db, project, key)
    db.commit()
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "memory entry not found")
    return {"deleted": True}


@router.delete("/projects/{project_id}/memory")
def clear_memory(project_id: str, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    project = _owned_project(db, project_id, user)
    n = db.query(MemoryEntry).filter(MemoryEntry.project_id == project.id).delete()
    db.commit()
    return {"deleted": int(n or 0)}
