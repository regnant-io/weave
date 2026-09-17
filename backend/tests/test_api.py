"""API-surface tests: health, library search, citation check, dataset profiling."""
from __future__ import annotations

import io


def test_health(app_client):
    res = app_client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["llm_engine"] == "offline"  # forced in tests


def test_readiness_checks_durable_dependencies(app_client):
    res = app_client.get("/ready")
    assert res.status_code == 200
    assert res.json() == {
        "status": "ready",
        "checks": {"database": True, "redis": True},
    }


def test_health_distinguishes_configured_from_reachable(app_client, monkeypatch):
    from app import main

    monkeypatch.setattr(main.settings, "render_service_url", "http://render:3100")
    monkeypatch.setattr(main, "_endpoint_reachable", lambda _url, timeout=0.35: False)
    body = app_client.get("/health").json()
    assert body["configured_capabilities"]["render_service"] is True
    assert body["capabilities"]["render_service"] is False


def test_project_with_default_canvas_can_be_deleted(app_client, auth_headers):
    """Creating a canvas must not make its parent project undeletable."""
    project = app_client.post(
        "/api/v1/projects",
        json={"title": "Disposable", "mode": "researcher"},
        headers=auth_headers,
    ).json()
    canvases = app_client.get(
        f"/api/v1/projects/{project['id']}/canvases", headers=auth_headers
    )
    assert canvases.status_code == 200
    assert len(canvases.json()) == 1

    deleted = app_client.delete(
        f"/api/v1/projects/{project['id']}", headers=auth_headers
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


def test_dataset_upload_and_profile(app_client, auth_headers):
    pid = app_client.post(
        "/api/v1/projects", json={"title": "P", "mode": "researcher"}, headers=auth_headers
    ).json()["id"]
    csv = b"region,value\nDodoma,10\nMwanza,20\nArusha,30\n"
    up = app_client.post(
        f"/api/v1/projects/{pid}/datasets",
        files={"file": ("regions.csv", io.BytesIO(csv), "text/csv")},
        headers=auth_headers,
    )
    assert up.status_code == 201, up.text
    body = up.json()
    assert body["row_count"] == 3
    assert body["status"] == "ready"
    cols = {c["name"] for c in body["column_profile"]["columns"]}
    assert {"region", "value"} <= cols


def test_citation_check_flags_predatory(app_client, auth_headers):
    res = app_client.post(
        "/api/v1/citations/check",
        json={"reference": "Published in OMICS International, guaranteed rapid publication."},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["flagged_predatory"] is True


def test_idempotent_upload_dedupes(app_client, auth_headers):
    pid = app_client.post(
        "/api/v1/projects", json={"title": "P2", "mode": "researcher"}, headers=auth_headers
    ).json()["id"]
    csv = b"x\n1\n2\n"
    headers = {**auth_headers, "Idempotency-Key": "fixed-key-123"}
    a = app_client.post(f"/api/v1/projects/{pid}/datasets",
                        files={"file": ("a.csv", io.BytesIO(csv), "text/csv")}, headers=headers)
    b = app_client.post(f"/api/v1/projects/{pid}/datasets",
                        files={"file": ("a.csv", io.BytesIO(csv), "text/csv")}, headers=headers)
    assert a.json()["id"] == b.json()["id"]


def test_idempotency_key_is_scoped_to_user_and_project(app_client, auth_headers):
    """A reused request key must never disclose another project's dataset."""
    import uuid

    first_pid = app_client.post(
        "/api/v1/projects", json={"title": "Owner", "mode": "researcher"},
        headers=auth_headers,
    ).json()["id"]
    key_headers = {**auth_headers, "Idempotency-Key": "shared-by-accident"}
    first = app_client.post(
        f"/api/v1/projects/{first_pid}/datasets",
        files={"file": ("first.csv", io.BytesIO(b"x\n1\n"), "text/csv")},
        headers=key_headers,
    )
    assert first.status_code == 201

    phone = "+2557" + uuid.uuid4().hex[:8]
    reg = app_client.post("/api/v1/auth/register", json={
        "phone": phone, "password": "password123", "role": "researcher",
    })
    second_headers = {
        "Authorization": f"Bearer {reg.json()['access_token']}",
        "Idempotency-Key": "shared-by-accident",
    }
    second_pid = app_client.post(
        "/api/v1/projects", json={"title": "Other", "mode": "researcher"},
        headers=second_headers,
    ).json()["id"]
    second = app_client.post(
        f"/api/v1/projects/{second_pid}/datasets",
        files={"file": ("second.csv", io.BytesIO(b"x\n2\n"), "text/csv")},
        headers=second_headers,
    )

    assert second.status_code == 201
    assert second.json()["id"] != first.json()["id"]
    assert second.json()["original_filename"] == "second.csv"
