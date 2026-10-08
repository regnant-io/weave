"""Weave's Ollama engine running on Cordon through the bridge transport.

Cordon is mocked at the HTTP layer, so what is checked is the translation
itself: Ollama's tool-call shape (object arguments, no ids) to OpenAI's and
back, the client identity Cordon admits the request under, and the receipt.
"""
import json

import httpx

from app.services.orchestration import cordon_bridge
from app.services.orchestration.cordon_bridge import CordonTransport


def _bridge(handler):
    t = CordonTransport("http://cordon.test:8443", client_id="weave", model="default",
                        num_ctx=32768, max_tokens=4096, timeout=10)
    t._http = httpx.Client(transport=httpx.MockTransport(handler))
    return httpx.Client(base_url="http://cordon.bridge", transport=t)


def test_tool_round_trip_is_translated_both_ways():
    seen = {}

    def cordon(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["client"] = request.headers.get("x-client-id")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "model": "default",
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None,
                "tool_calls": [{"index": 0, "id": "call_9", "type": "function",
                                "function": {"name": "run_python", "arguments": "{\"code\": \"1+1\"}"}}]}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 9},
            "cordon": {"request_id": "req-7", "signature": {"value": "sig"}},
        })

    client = _bridge(cordon)
    r = client.post("/api/chat", json={
        "model": "default",
        "stream": True,
        "options": {"num_predict": -1, "temperature": 0.4, "num_ctx": 32768},
        "tools": [{"type": "function", "function": {"name": "run_python", "parameters": {}}}],
        "messages": [
            {"role": "user", "content": "add"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "load_dataset", "arguments": {"id": 3}}}]},
            {"role": "tool", "tool_name": "load_dataset", "content": "{\"rows\": 10}"},
        ],
    })
    assert r.status_code == 200
    line = json.loads(r.text.strip().splitlines()[0])

    # To Cordon: OpenAI shape, ids minted and matched, arguments as JSON text.
    assert seen["url"] == "http://cordon.test:8443/openai/v1/chat/completions"
    assert seen["client"] == "weave"
    body = seen["body"]
    assert body["max_tokens"] == 4096           # num_predict -1 -> Cordon's ceiling
    assert body["stream"] is False
    call = body["messages"][1]["tool_calls"][0]
    assert call["function"]["arguments"] == json.dumps({"id": 3})
    assert body["messages"][2] == {"role": "tool", "tool_call_id": call["id"], "content": "{\"rows\": 10}"}

    # Back to Weave: Ollama shape, object arguments, done.
    assert line["done"] is True
    assert line["message"]["tool_calls"] == [{"function": {"name": "run_python", "arguments": {"code": "1+1"}}}]
    assert line["eval_count"] == 9
    assert cordon_bridge.last_receipt()["request_id"] == "req-7"


def test_refusal_is_reported_not_swallowed():
    def cordon(request):
        return httpx.Response(403, json={"error": {"message": "client weave is not enrolled"}})

    r = _bridge(cordon).post("/api/chat", json={"model": "default", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 403
    assert "not enrolled" in r.json()["error"]


def test_liveness_and_models():
    def cordon(request):
        if request.url.path == "/v1/health":
            return httpx.Response(200, json={"status": "healthy", "serving": True})
        return httpx.Response(200, json={"object": "list", "data": [{"id": "qwen2.5:7b"}]})

    client = _bridge(cordon)
    assert client.get("/api/version").status_code == 200
    names = [m["name"] for m in client.get("/api/tags").json()["models"]]
    assert names[0] == "default" and "qwen2.5:7b" in names
    show = client.post("/api/show", json={"model": "default"}).json()
    assert "tools" in show["capabilities"]
