"""Channel adapters (architecture §11: WhatsApp Business as a v2 add-on).

The orchestrator is deliberately channel-agnostic — it doesn't assume a browser —
so a WhatsApp message is just another way to reach `run_turn`. This adapter:
  * verifies the Meta webhook (GET),
  * receives inbound messages (POST), maps the sender's phone to a user + a
    dedicated 'WhatsApp' project, runs one non-streaming turn, and replies via the
    WhatsApp Cloud API (logs the reply when no token is configured).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Project, User
from ..security import hash_password
from ..services.orchestration import get_orchestrator

router = APIRouter()
log = logging.getLogger("weave.whatsapp")


@router.get("/whatsapp")
def verify(request: Request) -> Response:
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == settings.whatsapp_verify_token:
        return Response(content=q.get("hub.challenge", ""), media_type="text/plain")
    return Response(status_code=403)


@router.post("/whatsapp")
async def receive(request: Request, db: Session = Depends(get_db)) -> dict:
    body = await request.json()
    try:
        value = body["entry"][0]["changes"][0]["value"]
        msg = value["messages"][0]
        phone = msg["from"]
        text = msg.get("text", {}).get("body", "")
    except (KeyError, IndexError, TypeError):
        return {"status": "ignored"}
    if not text:
        return {"status": "no-text"}

    user = _get_or_create_user(db, phone)
    project = _get_or_create_wa_project(db, user)
    # WhatsApp users get a lightweight, direct experience.
    msg_out = get_orchestrator().run_turn(db, project, text, user.preferred_language or "sw",
                                          effort="spool")
    reply = (msg_out.content_sw if (user.preferred_language or "sw") == "sw" else msg_out.content_en)
    _send_whatsapp(phone, reply[:4000])
    return {"status": "ok"}


def _get_or_create_user(db: Session, phone: str) -> User:
    wa_phone = f"wa:{phone}"
    user = db.query(User).filter(User.phone == wa_phone).first()
    if not user:
        user = User(phone=wa_phone, password_hash=hash_password("wa-" + phone),
                    role="student", preferred_language="sw", phone_verified=True,
                    trust_tier="verified")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def _get_or_create_wa_project(db: Session, user: User) -> Project:
    project = (db.query(Project).filter(Project.user_id == user.id, Project.title == "WhatsApp")
               .first())
    if not project:
        project = Project(user_id=user.id, title="WhatsApp", mode="student",
                          hypotheses=[], summary="", notes=[])
        db.add(project)
        db.commit()
        db.refresh(project)
    return project


def _send_whatsapp(phone: str, text: str) -> None:
    if not (settings.whatsapp_token and settings.whatsapp_phone_id):
        log.info("[whatsapp reply -> %s] %s", phone, text[:200])
        return
    try:
        import httpx
        httpx.post(
            f"https://graph.facebook.com/v20.0/{settings.whatsapp_phone_id}/messages",
            headers={"Authorization": f"Bearer {settings.whatsapp_token}",
                     "Content-Type": "application/json"},
            json={"messaging_product": "whatsapp", "to": phone,
                  "type": "text", "text": {"body": text}},
            timeout=20,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("whatsapp send failed: %s", exc)
