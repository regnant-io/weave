"""API-surface tests: health, library search, citation check, dataset profiling."""
from __future__ import annotations

import io


def test_health(app_client):
    res = app_client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["llm_engine"] == "offline"  # forced in tests


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
