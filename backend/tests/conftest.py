"""Test fixtures.

Each test session runs against a throwaway SQLite database and forces the offline
LLM engine so the whole platform is testable with zero external services (the CI
requirement in architecture section 12).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Configure the app BEFORE importing it.
_tmp = Path(tempfile.mkdtemp(prefix="weave_test_"))
os.environ["WEAVE_DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["WEAVE_STORAGE_LOCAL_DIR"] = str(_tmp / "storage")
os.environ["WEAVE_FORCE_OFFLINE_LLM"] = "true"
os.environ["WEAVE_SECRET_KEY"] = "test-secret-key-deterministic"


@pytest.fixture(scope="session")
def app_client():
    from fastapi.testclient import TestClient
    from app.db import init_db
    from app.main import app

    init_db()
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="session")
def db_session():
    from app.db import SessionLocal, init_db
    init_db()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def auth_headers(app_client):
    import uuid
    phone = "+2557" + uuid.uuid4().hex[:8]
    res = app_client.post("/api/v1/auth/register", json={
        "phone": phone, "password": "password123", "role": "researcher",
        "preferred_language": "en",
    })
    assert res.status_code == 201, res.text
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
