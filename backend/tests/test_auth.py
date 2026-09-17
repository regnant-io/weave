"""Auth flow tests: register, login, OTP, protected route."""
from __future__ import annotations

import uuid


def test_register_and_me(app_client):
    phone = "+2557" + uuid.uuid4().hex[:8]
    res = app_client.post("/api/v1/auth/register", json={
        "phone": phone, "password": "password123", "preferred_language": "sw",
    })
    assert res.status_code == 201, res.text
    token = res.json()["access_token"]
    assert res.json()["user"]["trust_tier"] == "anonymous"
    me = app_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["phone"] == phone


def test_registration_unique_constraint_race_returns_conflict():
    """Two requests can both pass the optimistic lookup before either inserts."""
    import pytest
    from fastapi import HTTPException
    from sqlalchemy.exc import IntegrityError

    from app.api.auth import register
    from app.schemas import RegisterRequest

    class EmptyQuery:
        def filter(self, *_args, **_kwargs):
            return self

        def first(self):
            return None

    class RacingSession:
        rolled_back = False

        def query(self, *_args, **_kwargs):
            return EmptyQuery()

        def add(self, _row):
            pass

        def commit(self):
            raise IntegrityError("INSERT users", {}, RuntimeError("unique"))

        def rollback(self):
            self.rolled_back = True

    db = RacingSession()
    with pytest.raises(HTTPException) as exc:
        register(RegisterRequest(phone="+255700008888", password="password123"), db)
    assert exc.value.status_code == 409
    assert db.rolled_back is True


def test_refresh_tokens_rotate_and_reuse_revokes_the_family(app_client):
    phone = "+2557" + uuid.uuid4().hex[:8]
    issued = app_client.post("/api/v1/auth/register", json={
        "phone": phone, "password": "password123",
    }).json()
    old_refresh = issued["refresh_token"]
    rotated = app_client.post("/api/v1/auth/refresh", json={
        "refresh_token": old_refresh,
    })
    assert rotated.status_code == 200, rotated.text
    new_access = rotated.json()["access_token"]
    assert rotated.json()["refresh_token"] != old_refresh
    assert app_client.get("/api/v1/auth/me", headers={
        "Authorization": f"Bearer {new_access}",
    }).status_code == 200

    reuse = app_client.post("/api/v1/auth/refresh", json={
        "refresh_token": old_refresh,
    })
    assert reuse.status_code == 401
    assert app_client.get("/api/v1/auth/me", headers={
        "Authorization": f"Bearer {new_access}",
    }).status_code == 401


def test_logout_revokes_server_session(app_client):
    phone = "+2557" + uuid.uuid4().hex[:8]
    token = app_client.post("/api/v1/auth/register", json={
        "phone": phone, "password": "password123",
    }).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert app_client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    assert app_client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_logout_can_revoke_by_refresh_token_without_access(app_client):
    phone = "+2557" + uuid.uuid4().hex[:8]
    issued = app_client.post("/api/v1/auth/register", json={
        "phone": phone, "password": "password123",
    }).json()
    response = app_client.post("/api/v1/auth/logout", json={
        "refresh_token": issued["refresh_token"],
    })
    assert response.status_code == 200
    assert app_client.post("/api/v1/auth/refresh", json={
        "refresh_token": issued["refresh_token"],
    }).status_code == 401


def test_self_registration_cannot_claim_institutional_trust(app_client):
    """An institution id is an authorisation grant and needs verification."""
    phone = "+2557" + uuid.uuid4().hex[:8]
    res = app_client.post("/api/v1/auth/register", json={
        "phone": phone,
        "password": "password123",
        "institution_id": "claimed-without-proof",
    })
    assert res.status_code == 403


def test_institutional_trust_does_not_grant_global_admin_access():
    from fastapi import HTTPException
    import pytest

    from app.deps import get_admin_user
    from app.models import User

    user = User(phone="+255700000099", password_hash="x", role="researcher",
                trust_tier="institutional")
    with pytest.raises(HTTPException) as exc:
        get_admin_user(user)
    assert exc.value.status_code == 403


def test_whatsapp_signature_verification(monkeypatch):
    import hashlib
    import hmac

    from app.api.channels import _valid_whatsapp_signature
    from app.config import settings

    monkeypatch.setattr(settings, "whatsapp_app_secret", "test-app-secret")
    body = b'{"entry":[]}'
    sig = "sha256=" + hmac.new(b"test-app-secret", body, hashlib.sha256).hexdigest()

    assert _valid_whatsapp_signature(body, sig)
    assert not _valid_whatsapp_signature(body + b" ", sig)
    assert not _valid_whatsapp_signature(body, None)


def test_whatsapp_delivery_never_logs_as_success_in_production(monkeypatch):
    import pytest
    from app.api.channels import _send_whatsapp
    from app.config import settings

    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "whatsapp_token", None)
    monkeypatch.setattr(settings, "whatsapp_phone_id", None)
    with pytest.raises(RuntimeError, match="outbound credentials"):
        _send_whatsapp("255700000000", "reply")


def test_login_wrong_password_rejected(app_client):
    phone = "+2557" + uuid.uuid4().hex[:8]
    app_client.post("/api/v1/auth/register", json={"phone": phone, "password": "password123"})
    res = app_client.post("/api/v1/auth/login", json={"phone": phone, "password": "wrong"})
    assert res.status_code == 401


def test_protected_route_requires_token(app_client):
    assert app_client.get("/api/v1/projects").status_code == 401


def test_normal_user_cannot_replace_the_global_model_host(app_client, auth_headers):
    res = app_client.post("/api/v1/ollama", headers=auth_headers,
                          json={"host": "https://attacker.example"})
    assert res.status_code == 403


def test_operator_can_provision_an_explicit_admin(db_session):
    from app.cli import provision_admin

    phone = "+2557" + uuid.uuid4().hex[:8]
    user = provision_admin(db_session, phone, "a-long-admin-password")
    assert user.role == "admin"
    assert user.trust_tier == "institutional"
    assert user.phone_verified is True


def test_otp_flow(app_client):
    phone = "+2557" + uuid.uuid4().hex[:8]
    req = app_client.post("/api/v1/auth/otp/request", json={"phone": phone})
    assert req.status_code == 200
    code = req.json()["dev_code"]  # exposed only in debug
    ver = app_client.post("/api/v1/auth/otp/verify", json={"phone": phone, "code": code})
    assert ver.status_code == 200
    assert ver.json()["user"]["phone_verified"] is True
    assert ver.json()["user"]["trust_tier"] == "verified"


def test_production_sms_failure_does_not_log_the_otp(monkeypatch, caplog):
    import pytest

    from app.api.auth import SmsDeliveryError, _send_sms
    from app.config import settings

    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "sms_provider", "log")
    with pytest.raises(SmsDeliveryError):
        _send_sms("+255700000000", "Weave verification code: 123456")
    assert "123456" not in caplog.text


# --------------------------------------------------------------------------- #
#  Credential-endpoint hardening                                              #
# --------------------------------------------------------------------------- #
#
# These are the routes where calling repeatedly IS the attack, and until
# recently none of them had any limit at all. Each test drives the actual
# mechanism rather than asserting a decorator is present, because the only
# version of this that matters is the one that fires under load.


def test_otp_code_is_burned_after_too_many_wrong_guesses(app_client, monkeypatch):
    """A six-digit code with unlimited attempts is arithmetic, not a secret.

    The per-code budget is the limit that actually bounds the search: a rate
    limit keyed on the caller slows one attacker and does nothing about a
    distributed attempt, whereas a code that has absorbed five wrong guesses is
    dead no matter how many addresses they arrived from.
    """
    from app.config import settings

    phone = "+255700009001"
    app_client.post("/api/v1/auth/otp/request", json={"phone": phone})

    for _ in range(settings.otp_max_attempts):
        res = app_client.post("/api/v1/auth/otp/verify",
                              json={"phone": phone, "code": "000000"})
        assert res.status_code == 400, res.text

    # The budget is spent. Even the RIGHT code must now be refused, or the
    # budget would only apply to attackers who give up.
    res = app_client.post("/api/v1/auth/otp/verify",
                          json={"phone": phone, "code": "000000"})
    assert res.status_code == 400
    assert "new one" in res.json()["detail"]


def test_burning_a_code_does_not_lock_the_phone_out(app_client):
    """Burning the CODE, not the number.

    Attaching the budget to the phone would let anyone lock a real person out
    of their own account by guessing badly on their behalf — turning a
    brute-force defence into a denial-of-service tool. Requesting a fresh code
    has to keep working.
    """
    phone = "+255700009002"
    app_client.post("/api/v1/auth/otp/request", json={"phone": phone})
    for _ in range(8):
        app_client.post("/api/v1/auth/otp/verify", json={"phone": phone, "code": "111111"})

    fresh = app_client.post("/api/v1/auth/otp/request", json={"phone": phone})
    assert fresh.status_code == 200
    code = fresh.json().get("dev_code")
    assert code, "dev_code is returned while WEAVE_DEBUG is on"

    res = app_client.post("/api/v1/auth/otp/verify", json={"phone": phone, "code": code})
    assert res.status_code == 200, res.text
    assert res.json()["access_token"]


def test_login_is_rate_limited(app_client, monkeypatch):
    """Password guessing is bounded, and so is the CPU it costs us.

    Verification is scrypt, so each attempt is 64MB and real CPU time on the
    server. An unlimited login endpoint is both an account-takeover route and a
    way to exhaust the box without ever guessing correctly.
    """
    from app import deps
    from app.ratelimit import TokenBucketLimiter

    monkeypatch.setattr(deps, "auth_limiter", TokenBucketLimiter(3, burst=3))

    codes = [
        app_client.post("/api/v1/auth/login",
                        json={"phone": "+255700009003", "password": "wrong"}).status_code
        for _ in range(6)
    ]
    assert 429 in codes, codes
    # And the refusal tells the caller when to come back.
    last = app_client.post("/api/v1/auth/login",
                           json={"phone": "+255700009003", "password": "wrong"})
    assert last.status_code == 429
    assert "Retry-After" in last.headers


def test_a_malformed_token_is_rejected_not_a_crash(app_client):
    """Garbage in an Authorization header is routine, not exceptional.

    Base64-decoding a malformed signature raises, and the exception used to
    escape the dependency — so a corrupt cookie produced a 500 with a traceback
    instead of a 401. Wrong status, noisy logs, and trivially triggerable.
    """
    for bad in ("", "not-a-token", "a.b.c", "a.b.!!!!", "x" * 400):
        res = app_client.get("/api/v1/auth/me",
                             headers={"Authorization": f"Bearer {bad}"})
        assert res.status_code == 401, (bad, res.status_code, res.text)


def test_storage_rejects_a_sibling_directory_escape():
    """`is_relative_to`, not a string prefix.

    With a root of `/var/storage`, the key `../storage-public/x` resolves to
    `/var/storage-public/x` — which passes a `startswith` check and is outside
    the root.
    """
    import tempfile
    from pathlib import Path

    import pytest

    from app.storage import LocalStorage

    base = Path(tempfile.mkdtemp())
    (base / "storage-public").mkdir()
    store = LocalStorage(str(base / "storage"))

    for key in ("../storage-public/x", "../../etc/passwd", "a/../../b"):
        with pytest.raises(ValueError):
            store._path(key)

    # Ordinary nested keys still work.
    assert store._path("visuals/p1/a.html").name == "a.html"
