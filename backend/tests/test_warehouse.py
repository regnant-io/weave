"""Warehouse (DuckDB) mass-analysis tests, incl. the read-only SQL guard."""
from __future__ import annotations

import io

import pytest

from app.services.warehouse.service import _is_read_only, get_warehouse


@pytest.mark.parametrize("sql,ok", [
    ("SELECT * FROM data", True),
    ("WITH x AS (SELECT 1) SELECT * FROM x", True),
    ("select region, avg(value) from data group by region", True),
    ("DROP TABLE data", False),
    ("SELECT * FROM read_csv('/etc/passwd')", False),
    ("ATTACH 'x.db'", False),
    ("SELECT 1; DELETE FROM data", False),
    ("INSERT INTO data VALUES (1)", False),
    ("COPY data TO '/tmp/x'", False),
])
def test_sql_read_only_guard(sql, ok):
    assert _is_read_only(sql)[0] is ok


def test_duckdb_query_over_dataset(app_client, auth_headers):
    # upload a dataset, then query it through the warehouse SQL path
    pid = app_client.post("/api/v1/projects", json={"title": "W", "mode": "researcher"},
                          headers=auth_headers).json()["id"]
    csv = b"region,value\nDodoma,10\nMwanza,20\nDodoma,30\n"
    ds_id = app_client.post(
        f"/api/v1/projects/{pid}/datasets",
        files={"file": ("r.csv", io.BytesIO(csv), "text/csv")}, headers=auth_headers,
    ).json()["id"]

    from app.db import SessionLocal
    from app.models import Dataset
    wh = get_warehouse()
    if not wh.enabled:
        pytest.skip("duckdb not installed")
    db = SessionLocal()
    try:
        ds = db.query(Dataset).filter(Dataset.id == ds_id).first()
        out = wh.query("SELECT region, SUM(value) AS total FROM data GROUP BY region ORDER BY region", dataset=ds)
    finally:
        db.close()
    assert out["status"] == "ok", out
    assert "region" in out["columns"] and "total" in out["columns"]
    totals = {row[0]: row[1] for row in out["rows"]}
    assert totals["Dodoma"] == 40
