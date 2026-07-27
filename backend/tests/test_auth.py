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
