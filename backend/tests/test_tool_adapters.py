"""Exercise real local service wiring through the registered tool boundary."""
from __future__ import annotations

import io
import tarfile

from app.services.tools import ToolContext, get_registry


def test_local_memory_canvas_skills_and_workspace_adapters(db_session, tmp_path, monkeypatch):
    from app.config import settings
    from app.models import Project, User
    from app.services.canvas.service import CanvasService
    from app.services.memory.service import MemoryService
    from app.services.skills import get_skills
    from app.services.workspace.service import WorkspaceService
    from app.storage import storage

    monkeypatch.setattr(settings, "environment", "desktop")
    monkeypatch.setattr(settings, "workspace_enabled", True)
    user = User(password_hash="adapter-test", trust_tier="verified")
    db_session.add(user)
    db_session.flush()
    project = Project(user_id=user.id, title="Adapter smoke", mode="researcher")
    db_session.add(project)
    db_session.commit()
    workspace = WorkspaceService()
    workspace.root = tmp_path / "workspaces"
    memory = MemoryService()
    thread = memory.active_thread(db_session, project)
    ctx = ToolContext(db=db_session, project=project, thread=thread,
                      trust="verified", services={"memory": memory,
                      "canvas": CanvasService(), "skills": get_skills(),
                      "workspace": workspace})
    registry = get_registry()

    def call(tool_name, **arguments):
        result = registry.execute(tool_name, ctx, arguments)
        assert result["status"] == "ok", (tool_name, result)
        return result

    call("remember", key="unit", content="Values are in metres")
    assert call("recall", query="metres")["entries"][0]["key"] == "unit"
    assert call("forget", key="unit")["removed"] is True
    assert call("recall", query="metres")["entries"] == []

    canvas = call("canvas_create", title="Study", content="Original sentence")
    cid = canvas["canvas_id"]
    assert call("canvas_read", canvas_id=cid)["content"] == "Original sentence"
    call("canvas_edit", canvas_id=cid, find="Original", replace="Revised")
    call("canvas_append", canvas_id=cid, text="\nConclusion")
    assert call("canvas_read", canvas_id=cid)["content"] == "Revised sentence\n\nConclusion"
    call("canvas_write", canvas_id=cid, content="Final document")
    assert any(c["canvas_id"] == cid for c in call("canvas_list")["canvases"])
    assert registry.execute("canvas_edit", ctx, {"canvas_id": cid, "find": "gone",
                                                "replace": "bad"})["status"] == "error"

    skills = call("list_skills")["skills"]
    assert skills
    assert call("read_skill", name=skills[0]["name"])["body"]

    call("workspace_write", path="src/data.json", content='{"value": 1}')
    call("workspace_edit", path="src/data.json", find="1", replace="2")
    assert call("workspace_read", path="src/data.json")["content"] == '{"value": 2}'
    assert call("workspace_verify", path="src/data.json")["valid"] is True
    assert call("workspace_glob", pattern="src/*.json")["count"] == 1
    assert call("workspace_grep", pattern="value")["matches"]
    assert call("workspace_list")["entries"]
    call("workspace_move", **{"from": "src/data.json", "to": "src/final.json"})
    packaged = call("workspace_package", name="smoke")["output_files"][0]
    with tarfile.open(fileobj=io.BytesIO(storage.get_bytes(packaged["s3_key"]))) as archive:
        assert "smoke/src/final.json" in archive.getnames()
    call("workspace_delete", path="src/final.json")
    assert registry.execute("workspace_read", ctx, {"path": "src/final.json"})["status"] == "error"


def test_visual_registry_adapters_ignore_source_sidecars(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.services.render import visuals
    from app.storage import LocalStorage

    monkeypatch.setattr(visuals, "storage", LocalStorage(str(tmp_path)))
    pid, vid = "project", "visual"
    visuals.save(pid, vid, "<html>scene</html>",
                 {"title": "Scene", "tool": "render_custom", "spec": {}},
                 source={"code": "draw()", "html": "<div>Scene</div>"})
    # An unrelated malformed sidecar should not become a phantom visual either.
    visuals.storage.put_bytes(f"visuals/{pid}/other.json", b"[]")
    events = []
    ctx = ToolContext(project=SimpleNamespace(id=pid, mode="researcher"),
                      trust="verified", services={"render": object()},
                      emit=lambda event, data: events.append((event, data)))
    registry = get_registry()
    result = registry.execute("list_visuals", ctx, {})
    assert result["status"] == "ok"
    assert len(result["visuals"]) == 1
    assert result["visuals"][0]["visual_id"] == vid
    assert registry.execute("present_visual", ctx, {"visual_id": vid})["status"] == "ok"
    assert events[0][1]["visual_id"] == vid
    assert registry.execute("delete_visual", ctx, {"visual_id": vid})["removed"] is True
    assert not visuals.load_source(pid, vid)
    assert registry.execute("list_visuals", ctx, {})["visuals"] == []
    assert registry.execute("present_visual", ctx, {"visual_id": vid})["status"] == "error"


def test_pdf_without_converter_is_unavailable_before_rendering(monkeypatch):
    from app.config import settings
    from app.services.render.client import RenderClient
    from app.services.tools.base import ToolRegistry
    from app.services.tools.builtin import register_all

    monkeypatch.setattr(settings, "gotenberg_url", None)
    client = RenderClient()
    monkeypatch.setattr(client, "_post", lambda *_args, **_kwargs:
                        (_ for _ in ()).throw(AssertionError("must not render")))
    result = client.deck([{"title": "Demo"}], fmt="pdf")
    assert result["status"] == "unavailable"
    assert result["code"] == "pdf_export_unavailable"
    assert "html" in result["error"]
    registry = ToolRegistry()
    register_all(registry)
    schema = registry.get("generate_deck").schema()
    assert schema["input_schema"]["properties"]["format"]["enum"] == ["html"]
    assert "PDF export is unavailable" in schema["description"]
