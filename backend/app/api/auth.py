"""Auth routes (architecture 2 / 5.2): email/password + SMS OTP, JWT.

SMS OTP delivery is abstracted — in dev the code is logged (and returned in the
response only when WEAVE_DEBUG is on) instead of hitting an SMS gateway. Wire an
Africa's-Talking / Twilio client into `_send_sms` for production.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import enforce_auth_limit, enforce_session_limit, get_current_user
from ..models import AdminInvitation, AuthSession, OtpCode, User
from ..schemas import (
    AdminInviteAccept, LoginRequest, LogoutRequest, OtpRequestBody, OtpVerifyBody, RefreshRequest,
    RegisterRequest, TokenResponse, UserOut, UserPrefsIn,
)
from ..security import (
    create_access_token, decode_access_token, generate_otp, hash_otp, hash_password,
    hash_refresh_token, new_refresh_token, verify_password,
)

router = APIRouter()
log = logging.getLogger("weave.auth")


class SmsDeliveryError(RuntimeError):
    pass


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _issue_session(db: Session, user: User, family_id: str | None = None) -> TokenResponse:
    import uuid
    raw = new_refresh_token()
    row = AuthSession(
        family_id=family_id or uuid.uuid4().hex, user_id=user.id,
        refresh_hash=hash_refresh_token(raw),
        expires_at=datetime.now(timezone.utc) + timedelta(
            seconds=settings.refresh_token_ttl_seconds),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return TokenResponse(
        access_token=create_access_token(user.id, {"role": user.role}, session_id=row.id),
        refresh_token=raw, user=UserOut.model_validate(user),
    )


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
            r.raise_for_status()
            log.info("SMS via AfricasTalking to %s: %s", phone, r.status_code)
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("AfricasTalking send failed: %s", exc)
            raise SmsDeliveryError("SMS provider rejected the message") from exc
    if settings.sms_provider == "log" and not settings.is_deployed:
        log.info("SMS to %s: %s", phone, message)
        return
    # Never put a live login code into production logs. An unconfigured or
    # unknown provider is an unavailable feature, not a successful delivery.
    raise SmsDeliveryError("SMS delivery is not configured")


@router.post("/register", response_model=TokenResponse, status_code=201,
             dependencies=[Depends(enforce_auth_limit)])
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    # Institutional membership is an authorisation grant, not profile data.
    # Accepting a caller-supplied institution id used to promote any new account
    # to institutional trust, which also exposed privileged tools and the ops
    # dashboard.  Membership must come from a verified IdP/admin workflow.
    if body.institution_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "institutional membership must be provisioned by an administrator",
        )
    if db.query(User).filter(User.phone == body.phone).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "phone already registered")
    if body.email and db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered")

    user = User(
        phone=body.phone, email=body.email, password_hash=hash_password(body.password),
        role=body.role, preferred_language=body.preferred_language,
        institution_id=None,
        trust_tier="anonymous",
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        # The lookup above gives the common path a precise message, but it cannot
        # serialize two registrations that arrive together. The database unique
        # constraints are the authority; translate their race result instead of
        # leaking a 500 after both requests passed the optimistic lookup.
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "phone or email already registered",
        ) from exc
    db.refresh(user)
    return _issue_session(db, user)


@router.post("/login", response_model=TokenResponse,
             dependencies=[Depends(enforce_auth_limit)])
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.phone == body.phone).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid phone or password")
    return _issue_session(db, user)


@router.post("/otp/request", dependencies=[Depends(enforce_auth_limit)])
def request_otp(body: OtpRequestBody, db: Session = Depends(get_db)) -> dict:
    code = generate_otp()
    otp = OtpCode(
        phone=body.phone, code_hash=hash_otp(code),
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=settings.otp_ttl_seconds),
    )
    db.add(otp)
    db.commit()
    try:
        _send_sms(body.phone, f"Weave verification code: {code}")
    except SmsDeliveryError as exc:
        otp.consumed = True
        db.add(otp)
        db.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    resp = {"sent": True, "expires_in": settings.otp_ttl_seconds}
    if settings.debug:  # dev convenience only
        resp["dev_code"] = code
    return resp


@router.post("/otp/verify", response_model=TokenResponse,
             dependencies=[Depends(enforce_auth_limit)])
def verify_otp(body: OtpVerifyBody, db: Session = Depends(get_db)) -> TokenResponse:
    """Exchange a one-time code for a session.

    TWO INDEPENDENT LIMITS, BECAUSE ONE IS NOT ENOUGH.

    A six-digit code has a million values and lives for ten minutes. With
    unlimited attempts, guessing it is arithmetic: a script walks the space and
    takes over the account. Neither limit here would be sufficient alone.

      * The rate limit above is keyed on the CLIENT ADDRESS, and slows any one
        caller. It does nothing about a distributed attempt.
      * The attempt budget below is attached to THE CODE, so a code that has
        absorbed five wrong guesses is burned no matter how many addresses the
        guesses arrived from. That is the limit that actually bounds the search.

    The budget is deliberately on the code and not on the phone number: burning
    a number would let anyone lock a real person out of their own account by
    guessing badly on their behalf, which turns a brute-force defence into a
    denial-of-service tool. Burning a code only costs the legitimate user a
    fresh "send me another one".
    """
    otp = (
        db.query(OtpCode)
        .filter(OtpCode.phone == body.phone, OtpCode.consumed == False)  # noqa: E712
        .order_by(OtpCode.created_at.desc())
        .first()
    )
    if not otp:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid code")

    if (otp.attempts or 0) >= settings.otp_max_attempts:
        otp.consumed = True
        db.add(otp)
        db.commit()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "too many incorrect attempts for that code — request a new one",
        )

    if otp.code_hash != hash_otp(body.code):
        otp.attempts = (otp.attempts or 0) + 1
        db.add(otp)
        db.commit()
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
                    phone_verified=True, trust_tier="verified")
        db.add(user)
    else:
        user.phone_verified = True
    if user.trust_tier == "anonymous":
        user.trust_tier = "verified"
    db.commit()
    db.refresh(user)
    return _issue_session(db, user)


@router.post("/refresh", response_model=TokenResponse,
             dependencies=[Depends(enforce_session_limit)])
def refresh(body: RefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    token_hash = hash_refresh_token(body.refresh_token)
    finder = db.query(AuthSession).filter(AuthSession.refresh_hash == token_hash)
    if not settings.is_sqlite:
        finder = finder.with_for_update()
    current = finder.first()
    now = datetime.now(timezone.utc)
    if current is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token")
    if current.revoked_at is not None:
        # Reuse of a rotated token signals theft. Burn the complete family so
        # neither the attacker nor the original browser keeps a live session.
        if current.replaced_by_id:
            db.query(AuthSession).filter(AuthSession.family_id == current.family_id).update(
                {AuthSession.revoked_at: now}, synchronize_session=False,
            )
            db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh token was already used")
    if _aware(current.expires_at) <= now:
        current.revoked_at = now
        db.add(current)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh token expired")
    user = db.get(User, current.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user no longer exists")
    current.revoked_at = now
    current.last_used_at = now
    response = _issue_session(db, user, family_id=current.family_id)
    replacement = db.query(AuthSession).filter(
        AuthSession.refresh_hash == hash_refresh_token(response.refresh_token or ""),
    ).first()
    current.replaced_by_id = replacement.id if replacement else None
    db.add(current)
    db.commit()
    return response


@router.post("/logout")
def logout(body: LogoutRequest | None = None,
           authorization: str | None = Header(default=None),
           db: Session = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc)
    changed = False
    token = authorization.split(" ", 1)[1] if authorization and " " in authorization else ""
    payload = decode_access_token(token)
    if payload and payload.get("sid"):
        row = db.get(AuthSession, str(payload["sid"]))
        if row and row.user_id == payload.get("sub"):
            row.revoked_at = now
            db.add(row)
            changed = True
    # The access token may already be expired when the user presses Log out.
    # The still-valid refresh credential is the authoritative session handle.
    if body and body.refresh_token:
        row = db.query(AuthSession).filter(
            AuthSession.refresh_hash == hash_refresh_token(body.refresh_token),
        ).first()
        if row:
            db.query(AuthSession).filter(AuthSession.family_id == row.family_id).update(
                {AuthSession.revoked_at: now}, synchronize_session=False,
            )
            changed = True
    if changed:
        db.commit()
    return {"revoked": True}


@router.post("/admin-invite/accept", response_model=UserOut)
def accept_admin_invite(body: AdminInviteAccept, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)) -> UserOut:
    invite = db.query(AdminInvitation).filter(
        AdminInvitation.token_hash == hash_refresh_token(body.token),
    ).first()
    if (invite is None or invite.used_at is not None
            or _aware(invite.expires_at) <= datetime.now(timezone.utc)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid or expired invitation")
    if invite.phone and invite.phone != user.phone:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invitation does not match this account")
    if invite.email and (invite.email.lower() != (user.email or "").lower()):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invitation does not match this account")
    if not invite.phone and not invite.email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invitation has no recipient")
    invite.used_at = datetime.now(timezone.utc)
    user.role = "admin"
    db.add_all([invite, user])
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


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
