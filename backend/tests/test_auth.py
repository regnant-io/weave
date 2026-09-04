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
    me = app_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["phone"] == phone


def test_login_wrong_password_rejected(app_client):
    phone = "+2557" + uuid.uuid4().hex[:8]
    app_client.post("/api/v1/auth/register", json={"phone": phone, "password": "password123"})
    res = app_client.post("/api/v1/auth/login", json={"phone": phone, "password": "wrong"})
    assert res.status_code == 401


def test_protected_route_requires_token(app_client):
    assert app_client.get("/api/v1/projects").status_code == 401


def test_otp_flow(app_client):
    phone = "+2557" + uuid.uuid4().hex[:8]
    req = app_client.post("/api/v1/auth/otp/request", json={"phone": phone})
    assert req.status_code == 200
    code = req.json()["dev_code"]  # exposed only in debug
    ver = app_client.post("/api/v1/auth/otp/verify", json={"phone": phone, "code": code})
    assert ver.status_code == 200
    assert ver.json()["user"]["phone_verified"] is True


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
