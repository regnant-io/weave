"""Tool registry + web-search safety tests."""
from __future__ import annotations

from app.services.tools import ToolContext, get_registry
from app.services.tools.base import Tool, ToolRegistry
from app.services.websearch.client import _is_safe_url


def test_builtin_tools_registered():
    reg = get_registry()
    names = {t.name for t in reg.all()}
    assert {"run_analysis", "search_library", "check_citation", "web_search", "deep_research"} <= names


def test_trust_and_service_gating():
    reg = get_registry()
    # anonymous, no services -> only tools that need no service and allow anon
    anon = reg.schemas(mode="researcher", trust="anonymous", services={})
    anon_names = {t["name"] for t in anon}
    assert "check_citation" in anon_names          # anon, no service
    assert "run_analysis" not in anon_names        # needs 'verified' + 'analysis'
    assert "web_search" not in anon_names          # needs websearch service

    # verified with analysis service -> run_analysis shows up
    verified = reg.schemas(mode="researcher", trust="verified",
                           services={"analysis": object()})
    assert "run_analysis" in {t["name"] for t in verified}
    # web tools still hidden without the websearch service wired
    assert "web_search" not in {t["name"] for t in verified}
    # ...and appear once it is
    with_web = reg.schemas(mode="researcher", trust="verified",
                           services={"websearch": object()})
    assert "web_search" in {t["name"] for t in with_web}


def test_registry_execute_unknown_tool_is_safe():
    reg = ToolRegistry()
    out = reg.execute("nope", ToolContext(), {})
    assert out["status"] == "error"


def test_registry_execute_catches_tool_exceptions():
    reg = ToolRegistry()

    def boom(ctx, inp):
        raise ValueError("kaboom")

    reg.register(Tool(name="boom", description="", input_schema={"type": "object"}, execute=boom))
    out = reg.execute("boom", ToolContext(), {})
    assert out["status"] == "error" and "kaboom" in out["error"]


def test_ssrf_guard_blocks_private_and_metadata():
    assert _is_safe_url("http://localhost/x")[0] is False
    assert _is_safe_url("http://127.0.0.1/x")[0] is False
    assert _is_safe_url("http://169.254.169.254/latest/meta-data")[0] is False
    assert _is_safe_url("http://10.0.0.5/internal")[0] is False
    assert _is_safe_url("ftp://example.com/x")[0] is False
    # a public IP literal is allowed (no DNS needed, avoids test flakiness)
    assert _is_safe_url("http://8.8.8.8/")[0] is True
