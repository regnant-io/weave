"""Regressions for failures that reached production.

Each test here corresponds to something that actually broke for a user, and the
docstring says what the symptom was — a bare assertion tells the next person
what is checked but not why it must never come back.
"""
from __future__ import annotations

import pytest


def test_models_endpoint_returns_objects_not_bare_strings():
    """The settings page crashed with minified React error #31.

    `/models` returns `[{name, context}]`, but a component rendered each entry
    directly as a React child — "object with keys {name, context}". The contract
    is fixed here so a client can rely on the shape; parsing lives in
    frontend/src/lib/models.ts so no component ever touches the wire format.
    """
    from app.api.config import list_models

    payload = list_models(_user=None)  # type: ignore[arg-type]
    assert isinstance(payload["models"], list)
    for entry in payload["models"]:
        assert isinstance(entry, dict)
        assert isinstance(entry["name"], str) and entry["name"]
        assert "context" in entry
    for key in ("current_model", "engine", "num_ctx_fallback", "num_ctx_ceiling"):
        assert key in payload


def test_workspace_path_traversal_is_contained():
    """A model-supplied path must never escape the project workspace.

    The model controls this string, so `../`, an absolute path, a Windows drive
    prefix and a nested escape all have to be rejected or normalised — one
    missed case is arbitrary host file write.
    """
    from app.services.workspace import get_workspace_service

    w = get_workspace_service()
    base = w.project_dir("traversal-test").resolve()

    for bad in ["../../etc/passwd", "a/../../../x", "..", "", "   "]:
        with pytest.raises(ValueError):
            w._resolve("traversal-test", bad)

    with pytest.raises(ValueError):
        w._resolve("traversal-test", "C:\\Windows\\win.ini")

    # A leading "/" means WORKSPACE root, not filesystem root, and must still
    # land inside the sandbox.
    inside = w._resolve("traversal-test", "/etc/passwd")
    assert base in inside.parents, "a rooted path must stay inside the workspace"

    ok = w._resolve("traversal-test", "src/deep/file.txt")
    assert base in ok.parents


def test_workspace_verify_catches_truncated_files():
    """A truncated generated file looks fine until someone opens it.

    This is the specific failure mode of long generation: the model stops
    mid-file and nothing notices. Verification must catch it for every kind of
    file the model commonly writes.
    """
    from app.services.workspace import get_workspace_service

    w = get_workspace_service()
    P = "verify-test"
    w.reset(P)
    try:
        cases = [
            ("ok.py", "def f():\n    return 1\n", True),
            ("bad.py", "def f():\n    return 1 +\n", False),
            ("ok.json", '{"a": 1}', True),
            ("bad.json", '{"a": 1,', False),
            ("truncated.js", "function f() {\n  const a = 1;\n", False),
            ("truncated.html", "<html><body><h1>hi</h1>", False),
            ("empty.txt", "", False),
        ]
        for name, body, expected in cases:
            w.write_file(P, name, body)
            result = w.verify_file(P, name)
            assert result["status"] == "ok", name
            assert result["valid"] is expected, f"{name}: {result}"
    finally:
        w.reset(P)


def test_workspace_edit_refuses_ambiguous_matches():
    """Silently editing the wrong occurrence is worse than failing.

    `workspace_edit` exists so the model can change code without rewriting whole
    files; a non-unique `find` must be an error, not a guess.
    """
    from app.services.workspace import get_workspace_service

    w = get_workspace_service()
    P = "edit-test"
    w.reset(P)
    try:
        w.write_file(P, "a.py", "x = 1\ny = 1\nz = 1\n")
        ambiguous = w.edit_file(P, "a.py", "= 1", "= 2")
        assert ambiguous["status"] == "error"
        assert "3 times" in ambiguous["error"]

        unique = w.edit_file(P, "a.py", "y = 1", "y = 99")
        assert unique["status"] == "ok"
        assert "y = 99" in w.read_file(P, "a.py")["content"]

        # Explicit opt-in still works.
        allall = w.edit_file(P, "a.py", "= 1", "= 7", replace_all=True)
        assert allall["status"] == "ok" and allall["replacements"] == 2
    finally:
        w.reset(P)


def test_ask_user_wait_is_interruptible():
    """A client disconnect must not leak a worker thread for the full timeout.

    `ask_user` parks the turn's worker on an Event. If the user closes the tab,
    the orchestrator's cancel Event fires and the wait has to return promptly —
    otherwise every abandoned turn pins a thread for fifteen minutes.
    """
    import threading
    import time

    from app.services.interaction import get_broker

    broker = get_broker()
    q = broker.open(user_id="u", project_id="p", payload={"questions": []})
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()

    started = time.monotonic()
    result = broker.wait(q, timeout=600, cancel=cancel)
    elapsed = time.monotonic() - started

    assert result is None
    assert elapsed < 5, f"cancel took {elapsed:.1f}s; it must abort promptly"


def test_ask_user_answer_is_scoped_to_the_asking_user():
    """Holding a question id must not be enough to answer someone else's turn."""
    from app.services.interaction import get_broker

    broker = get_broker()
    q = broker.open(user_id="owner", project_id="p", payload={"questions": []})
    assert broker.answer(q.id, "someone-else", {"answers": {}}) is False
    assert broker.answer(q.id, "owner", {"answers": {"a": "b"}}) is True
    broker.wait(q, timeout=1)


def test_thread_history_is_budgeted_against_the_real_window(db_session):
    """History must be trimmed by TOKEN COST, not by a fixed message count.

    A fixed last-N slice ignores how large the turns actually are: twelve long
    analyses overflow an 8k window while twelve one-liners waste a 128k one.
    Trimming must also be REPORTED, so the UI can say the beginning was dropped
    instead of the assistant appearing to forget.
    """
    import uuid

    from app.models import Message, Project, User
    from app.services.memory import get_memory_service

    db = db_session
    user = db.query(User).first()
    if user is None:
        user = User(phone="+255" + uuid.uuid4().hex[:9], password_hash="x", role="researcher")
        db.add(user)
        db.flush()

    project = Project(user_id=user.id, title="budget-test", mode="researcher",
                      hypotheses=[], summary="", notes=[])
    db.add(project)
    db.flush()

    memory = get_memory_service()
    thread = memory.create_thread(db, project, title="t")
    for _ in range(10):
        db.add(Message(project_id=project.id, thread_id=thread.id, role="user",
                       content_en="word " * 200, content_sw=""))
        db.add(Message(project_id=project.id, thread_id=thread.id, role="assistant",
                       content_en="reply " * 200, content_sw=""))
    db.flush()

    try:
        wide, wide_trimmed = memory.history_for(db, thread, "en", context_window=200_000)
        narrow, narrow_trimmed = memory.history_for(db, thread, "en", context_window=4_096)

        assert len(wide) == 20 and wide_trimmed is False
        assert len(narrow) < len(wide), "a small window must drop older turns"
        assert narrow_trimmed is True, "trimming must be reported, never silent"
        # The most RECENT turns are the ones kept.
        assert narrow[-1]["content"] == wide[-1]["content"]
    finally:
        db.delete(project)
        db.commit()
