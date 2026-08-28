"""Orchestration tests: full bilingual turn end-to-end on the offline engine,
guardrails, and the data-analysis loop driving the sandbox."""
from __future__ import annotations

import io

from app.services.orchestration import guardrails
from app.services.orchestration.router import classify


def test_router_classifies_data_question():
    d = classify("Please compute the correlation between income and yield", "researcher")
    assert d.intent == "data"
    assert d.needs_sandbox


def test_router_classifies_literature_question():
    d = classify("What does NBS say about the population, cite the source", "researcher")
    assert d.intent == "literature"
    assert d.needs_retrieval


def test_integrity_guard_triggers_in_student_mode():
    assert guardrails.triggers_integrity_guard("please write my essay for me", "student")
    assert not guardrails.triggers_integrity_guard("please write my essay for me", "researcher")


def test_grounding_guard_flags_ungrounded_stat():
    ok, note = guardrails.check_grounding("The population is 61.7% urban.", had_passages=False)
    assert not ok and note


def _make_project(app_client, auth_headers, mode="researcher"):
    res = app_client.post("/api/v1/projects", json={"title": "T", "mode": mode}, headers=auth_headers)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_non_streaming_turn_stores_bilingual_message(app_client, auth_headers):
    pid = _make_project(app_client, auth_headers)
    res = app_client.post(
        f"/api/v1/projects/{pid}/messages",
        json={"content": "Habari, naomba unieleze dhana ya wastani", "language": "sw", "stream": False},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["role"] == "assistant"
    assert body["content_sw"]  # answered in Swahili
    assert body["content_en"]  # other-language column also populated


def test_streaming_turn_emits_sse_events(app_client, auth_headers):
    pid = _make_project(app_client, auth_headers)
    with app_client.stream(
        "POST", f"/api/v1/projects/{pid}/messages",
        json={"content": "Explain the concept of a median", "language": "en"},
        headers=auth_headers,
    ) as res:
        assert res.status_code == 200
        text = "".join(res.iter_text())
    assert "event: meta" in text
    assert "event: token" in text
    assert "event: done" in text


def test_data_question_runs_sandbox_end_to_end(app_client, auth_headers):
    pid = _make_project(app_client, auth_headers)
    # upload a small dataset
    csv = b"income,yield\n100,10\n200,25\n300,40\n400,55\n"
    up = app_client.post(
        f"/api/v1/projects/{pid}/datasets",
        files={"file": ("d.csv", io.BytesIO(csv), "text/csv")},
        headers=auth_headers,
    )
    assert up.status_code == 201, up.text
    ds_id = up.json()["id"]

    res = app_client.post(
        f"/api/v1/projects/{pid}/messages",
        json={"content": "Analyse the correlation in this dataset", "language": "en",
              "dataset_id": ds_id, "stream": False},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    # the assistant turn should record a run_analysis tool call
    assert any(tc["name"] == "run_analysis" for tc in body["tool_calls"])
