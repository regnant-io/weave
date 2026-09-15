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
import hashlib
import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ..config import settings
from ..db import get_db
from ..models import OutboxEvent, Project, User, WebhookReceipt
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


def _valid_whatsapp_signature(body: bytes, signature: str | None) -> bool:
    """Verify Meta's ``X-Hub-Signature-256`` over the exact request bytes."""
    secret = settings.whatsapp_app_secret
    if not secret or not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.removeprefix("sha256="))


@router.post("/whatsapp")
async def receive(
    request: Request,
    db: Session = Depends(get_db),
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
) -> dict:
    raw = await request.body()
    if not settings.whatsapp_app_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "WhatsApp webhook is not configured")
    if not _valid_whatsapp_signature(raw, x_hub_signature_256):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid webhook signature")
    try:
        import json
        body = json.loads(raw)
    except (ValueError, TypeError):
        return {"status": "ignored"}
    try:
        value = body["entry"][0]["changes"][0]["value"]
        msg = value["messages"][0]
        event_id = str(msg["id"])
        phone = msg["from"]
        text = msg.get("text", {}).get("body", "")
    except (KeyError, IndexError, TypeError):
        return {"status": "ignored"}
    if not text:
        return {"status": "no-text"}

    payload_hash = hashlib.sha256(raw).hexdigest()
    receipt = db.query(WebhookReceipt).filter(
        WebhookReceipt.provider == "whatsapp",
        WebhookReceipt.event_id == event_id,
    ).first()
    if receipt and receipt.status in {"processing", "completed"}:
        return {"status": "duplicate"}
    if receipt is None:
        receipt = WebhookReceipt(provider="whatsapp", event_id=event_id,
                                 payload_hash=payload_hash, status="processing")
        db.add(receipt)
    else:
        receipt.status = "processing"
        receipt.payload_hash = payload_hash
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"status": "duplicate"}

    try:
        user = _get_or_create_user(db, phone)
        project = _get_or_create_wa_project(db, user)
        # WhatsApp users get a lightweight, direct experience.
        msg_out = get_orchestrator().run_turn(
            db, project, text, user.preferred_language or "sw", effort="spool",
        )
        reply = (msg_out.content_sw if (user.preferred_language or "sw") == "sw"
                 else msg_out.content_en)
        event = OutboxEvent(
            topic="whatsapp.reply", aggregate_id=msg_out.id,
            dedupe_key=f"whatsapp-reply:{event_id}",
            payload={"phone": phone, "text": reply[:4000]}, status="pending",
        )
        db.add(event)
        receipt.status = "completed"
        db.add(receipt)
        db.commit()
        from ..tasks import dispatch
        job_id = dispatch("weave.deliver_outbox", event.id,
                          job_owner_id=user.id, job_project_id=project.id)
        return {"status": "accepted", "job_id": job_id}
    except Exception:
        db.rollback()
        current = db.get(WebhookReceipt, receipt.id)
        if current:
            current.status = "failed"
            db.add(current)
            db.commit()
        raise


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
        if settings.is_deployed:
            raise RuntimeError("WhatsApp outbound credentials are not configured")
        log.info("[whatsapp reply -> %s] %s", phone, text[:200])
        return
    import httpx
    response = httpx.post(
        f"https://graph.facebook.com/v20.0/{settings.whatsapp_phone_id}/messages",
        headers={"Authorization": f"Bearer {settings.whatsapp_token}",
                 "Content-Type": "application/json"},
        json={"messaging_product": "whatsapp", "to": phone,
              "type": "text", "text": {"body": text}},
        timeout=20,
    )
    response.raise_for_status()
