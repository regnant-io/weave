"""Real parsing/execution evidence across dataset runtime surfaces."""
from __future__ import annotations
import io
import json
from types import SimpleNamespace
import pytest
from app.services.analysis.profiling import PROFILE_ROWS, profile_dataset
from app.services.sandbox import get_sandbox_manager
from app.services.sandbox.datasets import read_dataset
from app.services.warehouse.service import get_warehouse

@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "cp1252"])
def test_encoded_csv_profile_python_and_sql_agree(tmp_path, monkeypatch, encoding):
    path = tmp_path / "encoded.csv"
    path.write_text("region,value\nCafé,10\nCafé,30\n", encoding=encoding)
    profile = profile_dataset(path)
    assert profile["available"], profile
    assert profile["row_count"] == 2
    assert read_dataset(path)["value"].sum() == 40
    result = get_sandbox_manager().run("df = weave_io.load_dataset()\nprint(df['region'][0])\nprint(int(df['value'].sum()))", dataset_path=path)
    assert result.status == "ok", result.stderr
    assert "Café" in result.stdout and "40" in result.stdout
    import app.services.warehouse.service as warehouse
    monkeypatch.setattr(warehouse.storage, "local_path", lambda _key: path)
    out = get_warehouse().query("SELECT SUM(value) FROM data", dataset=SimpleNamespace(s3_key="x", status="ready"))
    assert out["status"] == "ok", out
    assert out["rows"] == [[40]]

@pytest.mark.parametrize("text", [
    '[{"value": 10, "meta": {"site": "A"}}, {"value": 30, "meta": null}]',
    '{"value": [10, 30], "meta": [{"site": "A"}, null]}',
    '{"value": 10, "meta": {"site": "A"}}\n{"value": 30, "meta": null}\n',
])
def test_json_variations_and_nested_null_profile(tmp_path, text):
    path = tmp_path / "records.json"
    path.write_text(text, encoding="utf-8")
    profile = profile_dataset(path)
    assert profile["available"], profile
    columns = {c["name"]: c for c in profile["columns"]}
    assert profile["row_count"] == 2
    assert columns["meta"]["null"] == 1
    assert columns["meta"]["unique"] == 1
    assert columns["value"]["stats"]["mean"] == 20
    result = get_sandbox_manager().run("print(int(weave_io.load_dataset()['value'].sum()))", dataset_path=path)
    assert result.status == "ok", result.stderr
    assert result.stdout.strip() == "40"

def test_large_profile_declares_sampling_and_counts_tail_nulls_and_mixed_types(tmp_path):
    path = tmp_path / "large.csv"
    path.write_text("value,group\n" + "1,A\n" * PROFILE_ROWS + "bad,\n", encoding="utf-8")
    profile = profile_dataset(path)
    assert profile["available"], profile
    assert profile["row_count"] == PROFILE_ROWS + 1
    assert profile["sampled"] and profile["statistics_scope"] == "first_rows"
    columns = {c["name"]: c for c in profile["columns"]}
    assert columns["value"]["kind"] == "mixed"
    assert "stats" not in columns["value"]
    assert columns["group"]["null"] == 1
    assert profile["warnings"]

@pytest.mark.parametrize("text", ["a,b\n1,2,3\n", 'a,b\n"unterminated,2\n'])
def test_malformed_csv_fails_profile_and_execution_without_dropping_data(tmp_path, text):
    path = tmp_path / "bad.csv"
    path.write_text(text)
    assert not profile_dataset(path)["available"]
    result = get_sandbox_manager().run("print(weave_io.load_dataset())", dataset_path=path)
    assert result.status == "error", result.stdout

def test_nonfinite_profile_serializes_strict_json(tmp_path):
    path = tmp_path / "inf.csv"
    path.write_text("value\ninf\n-inf\n1\n")
    profile = profile_dataset(path)
    assert profile["available"], profile
    assert profile["columns"][0]["non_finite"] == 2
    json.dumps(profile, allow_nan=False)

def test_xlsx_and_parquet_execution_use_real_readers(tmp_path):
    import pandas as pd
    df = pd.DataFrame({"value": [10, 30], "region": ["A", "B"]})
    for suffix in ("xlsx", "parquet"):
        path = tmp_path / f"data.{suffix}"
        if suffix == "xlsx":
            df.to_excel(path, index=False)
        else:
            df.to_parquet(path, index=False)
        result = get_sandbox_manager().run("print(int(weave_io.load_dataset()['value'].sum()))", dataset_path=path)
        assert result.status == "ok", result.stderr
        assert result.stdout.strip() == "40"

def test_warehouse_external_function_alias_cannot_read_another_file(tmp_path, monkeypatch):
    import app.services.warehouse.service as warehouse
    path = tmp_path / "data.csv"
    path.write_text("value\n1\n")
    private = tmp_path / "private.csv"
    private.write_text("secret\nDO_NOT_EXPOSE\n")
    monkeypatch.setattr(warehouse.storage, "local_path", lambda _key: path)
    dataset = SimpleNamespace(s3_key="x", status="ready")
    out = get_warehouse().query(f"SELECT * FROM read_csv_auto('{private.as_posix()}')", dataset=dataset)
    assert out["status"] == "error", out
    assert "DO_NOT_EXPOSE" not in json.dumps(out)
    good = get_warehouse().query("SELECT SUM(value) FROM data", dataset=dataset)
    assert good["rows"] == [[1]]

def test_warehouse_reports_truncation_and_serializes_dates(tmp_path, monkeypatch):
    import app.services.warehouse.service as warehouse
    path = tmp_path / "data.csv"
    path.write_text("value\n1\n2\n3\n")
    monkeypatch.setattr(warehouse.storage, "local_path", lambda _key: path)
    out = get_warehouse().query("SELECT value, DATE '2026-09-26' AS day FROM data", dataset=SimpleNamespace(s3_key="x", status="ready"), max_rows=2)
    assert out["status"] == "ok", out
    assert out["truncated"] and out["row_count"] == 2
    assert out["rows"][0][1] == "2026-09-26"
    json.dumps(out, allow_nan=False)

def test_failed_upload_is_visible_and_cannot_be_analyzed(app_client, auth_headers):
    project = app_client.post("/api/v1/projects", json={"title": "Bad data", "mode": "researcher"}, headers=auth_headers).json()
    uploaded = app_client.post(f"/api/v1/projects/{project['id']}/datasets", files={"file": ("bad.csv", io.BytesIO(b"a,b\n1,2,3\n"), "text/csv")}, headers=auth_headers)
    assert uploaded.status_code == 201, uploaded.text
    dataset = uploaded.json()
    assert dataset["status"] == "error"
    assert "fields" in dataset["column_profile"]["reason"]
    run = app_client.post("/api/v1/analysis/run", json={"dataset_id": dataset["id"], "code": "print('made up')"}, headers=auth_headers)
    assert run.status_code == 409, run.text

def test_nonzero_exit_never_reports_success():
    result = get_sandbox_manager().run("raise SystemExit(2)")
    assert result.status == "error"
    assert "SystemExit" in result.stderr

def test_null_tokens_and_numeric_header_agree_across_csv_readers(tmp_path, monkeypatch):
    import app.services.warehouse.service as warehouse
    path = tmp_path / "data.csv"
    path.write_text("123,value\n1,10\n2,NA\n3,30\n")
    frame = read_dataset(path)
    assert list(frame.columns) == ["123", "value"]
    assert frame["value"].isna().sum() == 1
    monkeypatch.setattr(warehouse.storage, "local_path", lambda _key: path)
    out = get_warehouse().query('SELECT SUM(value), COUNT(value) FROM data', dataset=SimpleNamespace(s3_key="x", status="ready"))
    assert out["status"] == "ok", out
    assert out["rows"] == [[40, 2]]


def test_legacy_encoding_with_ascii_prefix_and_blank_lines(tmp_path):
    path = tmp_path / "data.csv"
    path.write_bytes(("\n\nvalue,region\n" + "1,A\n" * 40000 + "30,Café\n").encode("cp1252"))
    frame = read_dataset(path)
    assert len(frame) == 40001
    assert frame.iloc[-1]["region"] == "Café"
