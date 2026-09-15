"""Tool registry + web-search safety tests."""
from __future__ import annotations

from app.services.tools import ToolContext, get_registry
from app.services.tools.base import Tool, ToolRegistry
from app.services.websearch.client import _is_safe_url, _safe_get


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


def test_registry_validates_model_arguments_before_execution():
    reg = ToolRegistry()
    called = []
    reg.register(Tool(
        name="bounded", description="",
        input_schema={"type": "object", "required": ["query"], "properties": {
            "query": {"type": "string", "minLength": 2, "maxLength": 5},
            "limit": {"type": "integer", "minimum": 1, "maximum": 3},
        }},
        execute=lambda _ctx, inp: called.append(inp) or {"status": "ok"},
    ))
    out = reg.execute("bounded", ToolContext(), {"query": "x", "limit": 20})
    assert out["code"] == "invalid_tool_input"
    assert out["retryable"] is True
    assert called == []

    ok = reg.execute("bounded", ToolContext(), {"query": "valid", "limit": 2,
                                                  "note": "Searching"})
    assert ok["status"] == "ok"
    assert called == [{"query": "valid", "limit": 2}]


def test_registry_rejects_a_tool_that_was_not_advertised():
    """A hallucinated function name must not bypass intent/trust gating.

    Tool schemas guide the model, but the response from a model provider is
    still untrusted input.  Enforcement therefore belongs at execution too.
    """
    reg = ToolRegistry()
    called = []
    reg.register(Tool(
        name="dangerous", description="", input_schema={"type": "object"},
        execute=lambda _ctx, _inp: called.append(True) or {"status": "ok"},
    ))

    out = reg.execute(
        "dangerous", ToolContext(allowed_tools=frozenset({"safe"})), {},
    )

    assert out["status"] == "rejected"
    assert called == []


def test_registry_enforces_trust_and_services_at_execution():
    reg = ToolRegistry()
    reg.register(Tool(
        name="restricted", description="", input_schema={"type": "object"},
        execute=lambda _ctx, _inp: {"status": "ok"},
        trust_required="institutional", requires_services=("render",),
    ))

    low_trust = reg.execute("restricted", ToolContext(trust="verified"), {})
    no_service = reg.execute("restricted", ToolContext(trust="institutional"), {})

    assert low_trust["status"] == "rejected"
    assert no_service["status"] == "unavailable"


def test_ssrf_guard_blocks_private_and_metadata():
    assert _is_safe_url("http://localhost/x")[0] is False
    assert _is_safe_url("http://127.0.0.1/x")[0] is False
    assert _is_safe_url("http://169.254.169.254/latest/meta-data")[0] is False
    assert _is_safe_url("http://10.0.0.5/internal")[0] is False
    assert _is_safe_url("ftp://example.com/x")[0] is False
    # a public IP literal is allowed (no DNS needed, avoids test flakiness)
    assert _is_safe_url("http://8.8.8.8/")[0] is True


def test_ssrf_guard_rechecks_redirect_targets(monkeypatch):
    """A public URL redirecting to localhost must not bypass SSRF checks."""
    class Response:
        status_code = 302
        headers = {"location": "http://127.0.0.1/admin"}

    class FakeHttpx:
        @staticmethod
        def get(*_args, **_kwargs):
            return Response()

    # Keep the first hop deterministic and public without relying on DNS.
    import pytest
    with pytest.raises(ValueError, match="unsafe URL"):
        _safe_get(FakeHttpx, "http://8.8.8.8/start", timeout=1)


def test_safe_fetch_stops_a_stream_that_exceeds_the_byte_limit(monkeypatch):
    class Response:
        status_code = 200
        headers = {}

        def iter_bytes(self):
            yield b"1234"
            yield b"5678"

    class Context:
        def __enter__(self):
            return Response()

        def __exit__(self, *_args):
            return False

    class FakeHttpx:
        @staticmethod
        def stream(*_args, **_kwargs):
            return Context()

    import pytest
    with pytest.raises(ValueError, match="byte limit"):
        _safe_get(FakeHttpx, "http://8.8.8.8/data", timeout=1, max_bytes=6)
