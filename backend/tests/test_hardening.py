"""Regression tests for the desktop and orchestration hardening pass.

Each test names the failure it pins: what broke, and what the user saw.
"""
from __future__ import annotations

import json
import uuid

import pytest


# --------------------------------------------------------------------------- #
#  Desktop trust                                                               #
# --------------------------------------------------------------------------- #
def test_desktop_accounts_start_verified(app_client, monkeypatch):
    """Desktop sign-ups were `anonymous` with no SMS gateway to verify them, so
    every render, web and workspace tool was hidden and the model reported them
    "unavailable in this session"."""
    from app.config import settings

    monkeypatch.setattr(settings, "environment", "desktop")
    res = app_client.post("/api/v1/auth/register", json={
        "phone": "+2557" + uuid.uuid4().hex[:8], "password": "password123",
        "role": "researcher", "preferred_language": "en",
    })
    assert res.status_code == 201, res.text
    me = app_client.get("/api/v1/auth/me",
                        headers={"Authorization": f"Bearer {res.json()['access_token']}"})
    assert me.json()["trust_tier"] == "verified"


def test_server_accounts_still_start_anonymous(app_client):
    res = app_client.post("/api/v1/auth/register", json={
        "phone": "+2557" + uuid.uuid4().hex[:8], "password": "password123",
        "role": "researcher", "preferred_language": "en",
    })
    me = app_client.get("/api/v1/auth/me",
                        headers={"Authorization": f"Bearer {res.json()['access_token']}"})
    assert me.json()["trust_tier"] == "anonymous"


def test_existing_desktop_accounts_are_promoted(db_session, monkeypatch):
    from app.api.auth import promote_desktop_accounts
    from app.config import settings
    from app.models import User

    user = User(phone="+2559" + uuid.uuid4().hex[:8], password_hash="x", trust_tier="anonymous")
    db_session.add(user)
    db_session.commit()
    assert promote_desktop_accounts(db_session) == 0, "never on a server"
    monkeypatch.setattr(settings, "environment", "desktop")
    assert promote_desktop_accounts(db_session) >= 1
    db_session.refresh(user)
    assert user.trust_tier == "verified"


# --------------------------------------------------------------------------- #
#  Keyless desktop search                                                      #
# --------------------------------------------------------------------------- #
_DDG_HTML = """
<div class="result results_links results_links_deep result--ad">
  <a class="result__a" href="https://duckduckgo.com/y.js?ad_domain=x">Sponsored</a>
</div>
<div class="result results_links results_links_deep web-result ">
  <h2 class="result__title">
  <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fthinkingmachines.ai%2Ftinker%2F&amp;rut=abc">Tinker - <b>Thinking Machines</b> Lab</a>
  </h2>
  <a class="result__snippet" href="//duckduckgo.com/l/?uddg=x">A training API for <b>researchers</b>.</a>
</div>
<div class="result results_links web-result ">
  <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FThinking_Machines_Lab&amp;rut=def">Thinking Machines Lab - Wikipedia</a>
</div>
"""

_DDG_LITE = """
<a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fthinkingmachines.ai%2F&amp;rut=1" class='result-link'>Thinking Machines Lab</a>
<td class='result-snippet'>Research lab building <b>AI</b>.</td>
<a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fbuiltin.com%2Fa&amp;rut=2" class='result-link'>Inside Thinking Machines</a>
<td class='result-snippet'>Profile.</td>
"""


def test_duckduckgo_html_results_are_parsed_and_ads_dropped():
    from app.services.websearch.keyless import parse_ddg_html

    hits = parse_ddg_html(_DDG_HTML)
    assert [h.url for h in hits] == [
        "https://thinkingmachines.ai/tinker/",
        "https://en.wikipedia.org/wiki/Thinking_Machines_Lab",
    ]
    assert hits[0].title == "Tinker - Thinking Machines Lab"
    assert hits[0].snippet == "A training API for researchers ."


def test_duckduckgo_lite_results_are_parsed():
    from app.services.websearch.keyless import parse_ddg_lite

    hits = parse_ddg_lite(_DDG_LITE)
    assert [h.url for h in hits] == ["https://thinkingmachines.ai/", "https://builtin.com/a"]
    assert hits[0].snippet.startswith("Research lab")


def test_bing_fallback_drops_results_unrelated_to_the_query():
    """Bing RSS answered "thinking machines lab" with "How to get help in Windows"."""
    from app.services.websearch.keyless import Hit, relevant

    hits = [Hit("How to get help in Windows", "https://support.microsoft.com/x", "Tips app", "bing"),
            Hit("Thinking Machines Lab", "https://thinkingmachines.ai", "AI research", "bing")]
    assert [h.title for h in relevant(hits, "thinking machines lab")] == ["Thinking Machines Lab"]


class _Resp:
    def __init__(self, status, text="", payload=b""):
        self.status_code = status
        self.text = text
        self.content = payload or text.encode()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class _Httpx:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, **_kw):
        self.calls.append(url)
        for prefix, response in self.routes.items():
            if url.startswith(prefix):
                if isinstance(response, Exception):
                    raise response
                return response
        raise RuntimeError("no route")


def test_a_rate_limited_provider_falls_through_and_is_benched():
    from app.services.websearch.keyless import KeylessSearch

    fake = _Httpx({
        "https://html.duckduckgo.com": _Resp(202, "<div class='anomaly-modal'>"),
        "https://lite.duckduckgo.com": _Resp(200, _DDG_LITE),
    })
    search = KeylessSearch(fake)
    assert search.search("thinking machines", 5)[0].engine == "duckduckgo-lite"
    search.search("thinking machines", 5)
    assert sum(u.startswith("https://html.") for u in fake.calls) == 1, "not benched"


def test_an_outage_is_not_reported_as_no_results():
    """Folding "search is down" into [] made the model state a company had no
    public information."""
    from app.services.websearch.keyless import KeylessSearch, SearchOutage

    fake = _Httpx({"https://": ConnectionError("offline")})
    with pytest.raises(SearchOutage):
        KeylessSearch(fake).search("anything", 5)


def test_web_search_tool_reports_an_outage_as_an_error():
    from app.services.tools.base import ToolContext
    from app.services.tools.builtin import _web_search

    class Down:
        enabled = True

        def search_detailed(self, *_a, **_k):
            return [], "web search is unreachable right now (offline)"

    out = _web_search(ToolContext(services={"websearch": Down()}), {"query": "x"})
    assert out["status"] == "error"
    assert "do not conclude that no information exists" in out["error"]


# --------------------------------------------------------------------------- #
#  Desktop command execution                                                   #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("command, expected", [
    ("npm install && npm test", "npm install; if ($?) { npm test }"),
    ("cd app && npm i && npm run build", "cd app; if ($?) { npm i; if ($?) { npm run build } }"),
    ("a || b", "a; if (-not $?) { b }"),
    ('echo "x && y"', 'echo "x && y"'),
    ("if ($x) { a && b }", "if ($x) { a && b }"),
    ("plain", "plain"),
])
def test_bash_chaining_is_translated_for_windows_powershell(command, expected):
    """Windows PowerShell 5.1 rejects `&&` as a parse error, and it is the most
    common command shape a model writes."""
    from app.services.workspace.service import _ps51_chain

    assert _ps51_chain(command) == expected


@pytest.mark.parametrize("text, suffix, valid", [
    ("export default () => <p>Don't stop {x}</p>", ".tsx", True),
    ("<html><body><p>Let's go</p></body></html>", ".html", True),
    ("# Title\nIt's {unbalanced", ".md", True),
    ('const s = "a}b"; function f(){ return \'x)\' }', ".ts", True),
    ("function f(){ if (a) {", ".ts", False),
    ("<html><body><p>cut", ".html", False),
])
def test_structural_check_accepts_apostrophes_and_catches_truncation(text, suffix, valid):
    """An apostrophe in JSX or HTML text was read as an unterminated string, and
    the model was told a correct file did not parse."""
    from app.services.workspace.service import _structural_check

    assert _structural_check(text, suffix)["valid"] is valid


# --------------------------------------------------------------------------- #
#  Project checks                                                              #
# --------------------------------------------------------------------------- #
def test_checks_are_detected_from_the_manifest(tmp_path):
    from app.services.workspace.checks import detect, find_project_root

    app_dir = tmp_path / "todo"
    app_dir.mkdir()
    (app_dir / "package.json").write_text(json.dumps({
        "scripts": {"dev": "vite", "test": "vitest run", "build": "vite build",
                    "lint": "eslint ."},
        "devDependencies": {"typescript": "5", "vite": "5"},
    }))
    (app_dir / "tsconfig.json").write_text("{}")
    root = find_project_root(tmp_path)
    assert root == app_dir, "a project scaffolded into a subfolder is found"
    checks, _note = detect(root)
    assert [c.name for c in checks] == ["install", "typecheck", "lint", "test", "build"]
    assert checks[1].command == "npx tsc --noEmit"
    assert "dev" not in " ".join(c.command for c in checks)


def test_watch_mode_tests_are_never_run(tmp_path):
    from app.services.workspace.checks import detect

    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest --watch"}}))
    checks, note = detect(tmp_path)
    assert checks == [] and "watcher" in note


def test_checks_stop_at_the_first_failure(tmp_path):
    from app.services.workspace.checks import Check, run

    class Res:
        def __init__(self, code):
            self.status = "ok" if code == 0 else "error"
            self.exit_code = code
            self.stdout = ""
            self.stderr = "boom" if code else ""
            self.duration_ms = 1

    ran = []
    report = run(tmp_path, [Check("typecheck", "tsc"), Check("test", "t"), Check("build", "b")],
                 lambda cmd, _t: ran.append(cmd) or Res(1 if cmd == "t" else 0), "")
    result = report.as_result()
    assert ran == ["tsc", "t"]
    assert result["status"] == "error" and not result["passed"]
    assert "ROOT CAUSE" in result["hint"]


def test_a_missing_tool_is_skipped_not_failed(tmp_path):
    from app.services.workspace.checks import Check, run

    class Res:
        status, exit_code, duration_ms = "error", 1, 1
        stdout, stderr = "", "No module named pytest"

    result = run(tmp_path, [Check("test", "python -m pytest -q")], lambda *_: Res(), "").as_result()
    assert result["checks"][0]["status"] == "skipped"
    assert result["status"] == "unverified"


def test_placeholders_in_code_are_found_and_prose_is_ignored():
    from app.services.tools.workspace import _placeholders

    code = "function x(){\n  // ... rest of the code\n}\n// TODO: implement auth\n"
    assert len(_placeholders("src/a.js", code)) == 2
    assert _placeholders("README.md", "// ... rest of the code") == []
    assert _placeholders("a.py", "class A:\n    def f(self):\n        raise NotImplementedError\n") == []


# --------------------------------------------------------------------------- #
#  Artifact probe                                                              #
# --------------------------------------------------------------------------- #
def test_a_probe_that_cannot_open_the_document_is_not_an_artifact_defect():
    """Chromium refuses data: URLs over 2 MB. Every 3D artifact inlines its
    engine, so each was reported as "failed to load" and sent for repair."""
    from app.services.render.probe import ArtifactProbe

    result = ArtifactProbe._interpret(
        {"loaded": False, "loadError": "ERR_INVALID_URL (-300) loading 'data:text/html'"},
        heavy=True,
    )
    assert result.available is False and result.ok is True


def test_a_page_that_hangs_is_still_a_defect():
    from app.services.render.probe import ArtifactProbe

    result = ArtifactProbe._interpret({"loaded": False, "loadError": "page load timed out"},
                                      heavy=True)
    assert result.available is True and result.ok is False


# --------------------------------------------------------------------------- #
#  Engine plumbing                                                             #
# --------------------------------------------------------------------------- #
def test_oversized_tool_results_stay_valid_json():
    """Cutting the serialised result at 8000 characters handed the model an
    unterminated string and no closing braces."""
    from app.services.orchestration.llm import _stringify_tool_result

    out = _stringify_tool_result({"status": "ok", "content": "x" * 60000,
                                  "stderr": "E" * 50 + "the real error"})
    parsed = json.loads(out)
    assert len(out) <= 8000
    assert parsed["stderr"].endswith("the real error")
    assert "characters omitted" in parsed["content"]


def test_malformed_tool_arguments_are_reported_not_executed_as_empty():
    from app.services.orchestration.llm import _parse_tool_arguments

    args, problem = _parse_tool_arguments('{"path": "a.js", "content": "unterminated')
    assert args == {} and "not valid JSON" in problem
    assert _parse_tool_arguments('{"a": 1}') == ({"a": 1}, "")


class _StreamResponse:
    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_lines(self):
        yield from self._lines

    def raise_for_status(self):
        return None


class _Client:
    def __init__(self, scripts):
        self.scripts = list(scripts)

    def stream(self, *_a, **_k):
        return _StreamResponse(self.scripts.pop(0))


def _ollama(scripts):
    from app.services.orchestration.llm import OllamaEngine

    engine = OllamaEngine.__new__(OllamaEngine)
    engine._client = _Client(scripts)
    engine._tags_cache = (10**9, [{"name": "m", "capabilities": ["tools"],
                                    "details": {"parameter_size": "70B"}}])
    engine.effective_context = lambda _name: 8192
    engine.resolve_model = lambda name: name or "m"
    engine.model_for_tier = lambda _tier: "m"
    return engine


def test_cancelling_between_steps_does_not_crash_the_turn():
    """The cancel path returned the undefined name `final_text`: every Stop or
    steer that landed between steps raised NameError and the whole turn fell
    back to the offline engine."""
    import threading

    cancel = threading.Event()
    step = json.dumps({"message": {"content": "partial", "tool_calls": [
        {"function": {"name": "t", "arguments": {}}}]}, "done": True})

    def executor(_name, _args):
        cancel.set()
        return {"status": "ok"}

    result = _ollama([[step]]).generate(system="s", messages=[], tools=[{"name": "t"}],
                                        tool_executor=executor, tier="fast", cancel=cancel)
    assert result.text == "partial"


def test_output_cut_off_at_the_limit_is_recovered():
    first = json.dumps({"message": {"content": "Writing the file"}, "done": True,
                        "done_reason": "length"})
    second = json.dumps({"message": {"content": "Done in parts."}, "done": True,
                         "done_reason": "stop"})
    result = _ollama([[first], [second]]).generate(
        system="s", messages=[], tools=[], tool_executor=lambda *_: {}, tier="fast")
    assert "Done in parts." in result.text


# --------------------------------------------------------------------------- #
#  Render client                                                               #
# --------------------------------------------------------------------------- #
def test_a_rejected_chart_spec_reaches_the_model_verbatim(monkeypatch):
    """A 400 carrying "encoding refers to `Yield`, which is not in the data"
    used to surface as "HTTPStatusError: 400 Bad Request"."""
    import httpx

    from app.config import settings
    from app.services.render.client import RenderClient

    monkeypatch.setattr(settings, "render_service_url", "http://render.test")

    def handler(request):
        return httpx.Response(400, json={"error": "encoding refers to `Yield`, which is not in the data"})

    client = RenderClient()
    transport = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(client, "_httpx", type("H", (), {
        "post": staticmethod(lambda url, **kw: transport.post(url, **kw)),
        "TimeoutException": httpx.TimeoutException, "HTTPError": httpx.HTTPError,
    }))
    out = client.chart({"mark": "bar"})
    assert out["status"] == "error" and out["code"] == "invalid_spec"
    assert "`Yield`" in out["error"]


# --------------------------------------------------------------------------- #
#  Time awareness                                                              #
# --------------------------------------------------------------------------- #
def test_the_prompt_states_today_and_the_current_year():
    from app.services.clock import now
    from app.services.orchestration.prompts import assemble_system_prompt

    prompt = assemble_system_prompt(mode="researcher", language="en", passages=[],
                                    project_summary="", hypotheses=[], dataset_profile=None,
                                    capabilities={"websearch"})
    assert "CURRENT DATE" in prompt
    assert f"put {now().year} in the query" in prompt


@pytest.mark.parametrize("html, expected", [
    ('<meta property="article:published_time" content="2025-03-04T10:00:00Z">', "2025-03-04"),
    ('<script type="application/ld+json">{"datePublished":"2024-11-02T08:00"}</script>', "2024-11-02"),
    ('<meta name="citation_publication_date" content="2019/12/31">', "2019-12-31"),
    ('<time datetime="2023-06">June</time>', "2023-06"),
    ("<p>no date</p>", ""),
])
def test_pages_declare_when_they_were_published(html, expected):
    from app.services.clock import published_date

    assert published_date(html) == expected


def test_web_passages_show_their_date_to_the_model():
    from app.services.orchestration.prompts import build_grounding_layer

    layer = build_grounding_layer([{"source_type": "web", "title": "T", "content": "c",
                                    "published": "2024-11-02"}])
    assert "published 2024-11-02" in layer


def test_the_recency_round_searches_the_current_year():
    from app.services.clock import now
    from app.services.websearch.research import _refine

    assert _refine("thinking machines lab", [], 1).endswith(str(now().year))


# --------------------------------------------------------------------------- #
#  Artifact preview                                                            #
# --------------------------------------------------------------------------- #
def test_the_preview_url_is_signed_with_an_expiry():
    """The release path called sign_path() without its expiry: a TypeError the
    moment the probe produced a real screenshot, which crashed the whole turn
    into the offline fallback."""
    import base64
    from urllib.parse import parse_qs, urlparse
    from app.services.orchestration.inspection import store_preview
    from app.storage import storage

    url = store_preview(base64.b64encode(b"preview-image").decode())
    parsed = urlparse(url)
    assert "exp" in parse_qs(parsed.query)
    assert "sig" in parse_qs(parsed.query)
    key = parsed.path.split("/api/artifact/", 1)[-1]
    assert storage.get_bytes(key) == b"preview-image"
