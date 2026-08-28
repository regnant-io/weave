"""Auth routes (architecture 2 / 5.2): email/password + SMS OTP, JWT.

SMS OTP delivery is abstracted — in dev the code is logged (and returned in the
response only when WEAVE_DEBUG is on) instead of hitting an SMS gateway. Wire an
Africa's-Talking / Twilio client into `_send_sms` for production.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import OtpCode, User
from ..schemas import (
    LoginRequest, OtpRequestBody, OtpVerifyBody, RegisterRequest, TokenResponse,
    UserOut, UserPrefsIn,
)
from ..security import (
    create_access_token, generate_otp, hash_otp, hash_password, verify_password,
)

router = APIRouter()
log = logging.getLogger("weave.auth")


def _send_sms(phone: str, message: str) -> None:
    """Send an SMS. Providers: 'log' (dev — logs it) or 'africastalking'
    (broadly reachable in Tanzania — architecture §2)."""
    if settings.sms_provider == "africastalking" and settings.at_api_key and settings.at_username:
        try:
            import httpx
            r = httpx.post(
                "https://api.africastalking.com/version1/messaging",
                headers={"apiKey": settings.at_api_key, "Accept": "application/json",
                         "Content-Type": "application/x-www-form-urlencoded"},
                data={"username": settings.at_username, "to": phone, "message": message,
                      **({"from": settings.at_sender_id} if settings.at_sender_id else {})},
                timeout=15,
            )
            log.info("SMS via AfricasTalking to %s: %s", phone, r.status_code)
            return
        except Exception as exc:  # noqa: BLE001 - fall back to logging
            log.warning("AfricasTalking send failed (%s); logging instead", exc)
    log.info("SMS to %s: %s", phone, message)


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    if db.query(User).filter(User.phone == body.phone).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "phone already registered")
    if body.email and db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered")

    user = User(
        phone=body.phone, email=body.email, password_hash=hash_password(body.password),
        role=body.role, preferred_language=body.preferred_language,
        institution_id=body.institution_id,
        trust_tier="institutional" if body.institution_id else "verified",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user.id, {"role": user.role})
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.phone == body.phone).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid phone or password")
    token = create_access_token(user.id, {"role": user.role})
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/otp/request")
def request_otp(body: OtpRequestBody, db: Session = Depends(get_db)) -> dict:
    code = generate_otp()
    otp = OtpCode(
        phone=body.phone, code_hash=hash_otp(code),
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=settings.otp_ttl_seconds),
    )
    db.add(otp)
    db.commit()
    _send_sms(body.phone, f"Weave verification code: {code}")
    resp = {"sent": True, "expires_in": settings.otp_ttl_seconds}
    if settings.debug:  # dev convenience only
        resp["dev_code"] = code
    return resp


@router.post("/otp/verify", response_model=TokenResponse)
def verify_otp(body: OtpVerifyBody, db: Session = Depends(get_db)) -> TokenResponse:
    otp = (
        db.query(OtpCode)
        .filter(OtpCode.phone == body.phone, OtpCode.consumed == False)  # noqa: E712
        .order_by(OtpCode.created_at.desc())
        .first()
    )
    if not otp or otp.code_hash != hash_otp(body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid code")
    # SQLite returns tz-naive datetimes; normalise to UTC before comparing so the
    # comparison never mixes naive and aware datetimes (a TypeError otherwise).
    expires_at = otp.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "code expired")

    otp.consumed = True
    user = db.query(User).filter(User.phone == body.phone).first()
    if not user:
        # OTP-first signup: create a passwordless-until-set account
        user = User(phone=body.phone, password_hash=hash_password(generate_otp() + "!Aa"),
                    phone_verified=True)
        db.add(user)
    else:
        user.phone_verified = True
    db.commit()
    db.refresh(user)
    token = create_access_token(user.id, {"role": user.role})
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)


@router.patch("/me", response_model=UserOut)
def update_me(body: UserPrefsIn, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)) -> UserOut:
    """Update the signed-in user's own preferences.

    `allow_source_crawl` is the control over whether the public pages this
    user's sessions consult may be offered as crawl candidates for the shared
    library. Turning it off takes effect immediately and creates no further
    candidates; it does not retroactively remove ones already suggested, which
    is what the admin page's delete is for.
    """
    if body.preferred_language in {"sw", "en"}:
        user.preferred_language = body.preferred_language
    if body.allow_source_crawl is not None:
        user.allow_source_crawl = bool(body.allow_source_crawl)
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


@router.get("/saml/metadata")
def saml_metadata() -> dict:
    """Institutional SSO (SAML) endpoint (architecture v2 §13).

    Stubbed: wiring a specific IdP (UDSM/institution) requires their metadata and
    `python3-saml`. This documents the SP endpoints an institution would configure;
    the ACS below completes the assertion consumer flow once an IdP is registered.
    """
    return {
        "status": "not_configured",
        "sp_entity_id": "https://weave.tz/saml/metadata",
        "acs_url": "/api/v1/auth/saml/acs",
        "note": "Register an institutional IdP to enable SAML SSO (v2).",
    }


@router.post("/saml/acs")
def saml_acs() -> dict:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED,
                        "SAML SSO not configured — register an institutional IdP (v2).")
