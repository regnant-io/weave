"""Ollama engine tests.

These exercise the real OllamaEngine code path (tool-schema conversion, the
/api/chat tool-calling loop, translation, reachability) against a mocked HTTP
transport, so they verify the integration without a running Ollama server."""
from __future__ import annotations

import json

import httpx

from app.services.orchestration.llm import OllamaEngine
from app.services.tools import get_registry

# All registered tool schemas (ungated), used to exercise the Ollama tool loop.
TOOL_SCHEMAS = [t.schema() for t in get_registry().all()]


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://ollama.test")


def test_tool_schema_conversion_is_openai_style():
    tools = OllamaEngine._to_ollama_tools(TOOL_SCHEMAS)
    assert tools[0]["type"] == "function"
    fn = tools[0]["function"]
    assert fn["name"] == "run_analysis"
    assert "parameters" in fn and fn["parameters"]["type"] == "object"


def test_ping_true_and_false():
    ok = OllamaEngine(client=_client(lambda r: httpx.Response(200, json={"models": []})))
    assert ok.ping() is True

    def boom(_r):
        raise httpx.ConnectError("refused")

    down = OllamaEngine(client=_client(boom))
    assert down.ping() is False


def test_generate_plain_answer_no_tools():
    def handler(request):
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "Habari, jibu."}})

    eng = OllamaEngine(client=_client(handler))
    res = eng.generate(system="s", messages=[{"role": "user", "content": "hi"}],
                       tools=[], tool_executor=lambda n, a: {}, tier="fast")
    assert res.text == "Habari, jibu."
    assert res.tool_events == []


def test_generate_runs_tool_loop():
    calls = {"n": 0}

    def handler(request):
        body = json.loads(request.content)
        has_tool_result = any(m.get("role") == "tool" for m in body["messages"])
        if not has_tool_result:
            # first turn: ask to call run_analysis
            return httpx.Response(200, json={"message": {
                "role": "assistant", "content": "",
                "tool_calls": [{"function": {"name": "run_analysis",
                                             "arguments": {"code": "print(1)"}}}],
            }})
        # second turn: final answer after seeing the tool result
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "Done [S1]."}})

    def executor(name, args):
        calls["n"] += 1
        assert name == "run_analysis"
        assert args["code"] == "print(1)"
        return {"status": "ok", "stdout": "1", "output_files": []}

    eng = OllamaEngine(client=_client(handler))
    res = eng.generate(system="s", messages=[{"role": "user", "content": "analyse"}],
                       tools=TOOL_SCHEMAS, tool_executor=executor, tier="frontier")
    assert calls["n"] == 1
    assert res.text == "Done [S1]."
    assert res.tool_events[0]["name"] == "run_analysis"


def test_translate():
    def handler(request):
        return httpx.Response(200, json={"message": {"content": "Translated text"}})

    eng = OllamaEngine(client=_client(handler))
    assert eng.translate("maandishi", "en") == "Translated text"


def test_generate_handles_string_arguments():
    """Some models return tool-call arguments as a JSON string, not an object."""
    def handler(request):
        body = json.loads(request.content)
        if not any(m.get("role") == "tool" for m in body["messages"]):
            return httpx.Response(200, json={"message": {
                "role": "assistant", "content": "",
                "tool_calls": [{"function": {"name": "check_citation",
                                             "arguments": '{"reference": "OMICS"}'}}],
            }})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "ok"}})

    seen = {}

    def executor(name, args):
        seen.update(args)
        return {"status": "ok"}

    eng = OllamaEngine(client=_client(handler))
    eng.generate(system="s", messages=[{"role": "user", "content": "check"}],
                 tools=TOOL_SCHEMAS, tool_executor=executor, tier="fast")
    assert seen.get("reference") == "OMICS"
