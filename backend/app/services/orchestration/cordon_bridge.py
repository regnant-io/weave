"""Cordon behind Weave's Ollama engine.

Cordon is Regnant's confidential inference engine: it serves a local model with
one accountable way in — every request admitted under a client identity and
audited before it runs, every answer filtered and signed. It speaks OpenAI's
chat-completions protocol (tool calls included). Weave's agent loop speaks
Ollama's `/api/chat`.

Rather than a second copy of the agent loop, this module is an httpx transport
that answers the handful of Ollama routes `OllamaEngine` uses by calling
Cordon. The engine keeps its tool loop, context sizing, cut-off recovery and
event stream unchanged; only the wire underneath it is different.

    WEAVE_LLM_BACKEND=cordon
    WEAVE_CORDON_URL=http://127.0.0.1:8443
    WEAVE_CORDON_CLIENT_ID=weave        # enrolled in Cordon's clients.json
    WEAVE_CORDON_MODEL=default          # the model the node loaded
    WEAVE_CORDON_NUM_CTX=32768          # the runtime's context window

Translation notes:

* Ollama passes tool-call arguments as objects and answers tool calls without
  ids; OpenAI uses JSON strings and ids. Ids are minted per call and matched to
  the `tool` messages that follow, in order.
* `/api/chat` streaming is answered as one NDJSON line carrying the whole
  message. Cordon generates a tool-offering request whole anyway (a call is
  filtered complete), so nothing is lost; text-only turns arrive at once
  rather than token by token.
* `options.num_predict = -1` (run to a natural stop) becomes Cordon's
  per-client output ceiling, WEAVE_CORDON_MAX_TOKENS.
* Cordon's evidence (audit request ID, signature) is kept on the response
  under `cordon`, and the last receipt is available from `last_receipt()`.
"""
from __future__ import annotations

import json
import threading
from typing import Any

import httpx

_receipt_lock = threading.Lock()
_last_receipt: dict | None = None


def last_receipt() -> dict | None:
    """Cordon's evidence for the most recent answer, if any."""
    with _receipt_lock:
        return dict(_last_receipt) if _last_receipt else None


def _to_openai_messages(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    pending_ids: list[str] = []
    counter = 0
    for m in messages:
        role = m.get("role", "user")
        if role == "assistant" and m.get("tool_calls"):
            calls = []
            pending_ids = []
            for tc in m["tool_calls"]:
                fn = tc.get("function", {}) or {}
                counter += 1
                call_id = tc.get("id") or f"call_{counter}"
                pending_ids.append(call_id)
                args = fn.get("arguments", {})
                calls.append({
                    "id": call_id, "type": "function",
                    "function": {
                        "name": fn.get("name", ""),
                        "arguments": args if isinstance(args, str) else json.dumps(args),
                    },
                })
            out.append({"role": "assistant", "content": m.get("content") or None, "tool_calls": calls})
        elif role == "tool":
            call_id = m.get("tool_call_id") or (pending_ids.pop(0) if pending_ids else f"call_{counter}")
            out.append({"role": "tool", "tool_call_id": call_id, "content": m.get("content", "")})
        else:
            content = m.get("content", "")
            # Images are not served by Cordon (text models); they are dropped
            # from the request rather than sent to be refused.
            out.append({"role": role, "content": content})
    return out


def _from_openai_tool_calls(calls: list[dict] | None) -> list[dict]:
    result = []
    for tc in calls or []:
        fn = tc.get("function", {}) or {}
        raw = fn.get("arguments", "{}")
        try:
            args = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            args = raw  # Weave's _parse_tool_arguments reports it as malformed
        result.append({"function": {"name": fn.get("name", ""), "arguments": args}})
    return result


class CordonTransport(httpx.BaseTransport):
    """Answers OllamaEngine's routes from a Cordon node."""

    def __init__(self, base_url: str, client_id: str, model: str,
                 num_ctx: int, max_tokens: int, timeout: float,
                 cert: tuple[str, str] | None = None, verify: Any = True) -> None:
        self.base = base_url.rstrip("/")
        self.client_id = client_id
        self.model = model or "default"
        self.num_ctx = num_ctx
        self.max_tokens = max_tokens
        kwargs: dict[str, Any] = {"timeout": timeout, "verify": verify}
        if cert:
            kwargs["cert"] = cert
        self._http = httpx.Client(**kwargs)

    # -- helpers ------------------------------------------------------------
    def _headers(self) -> dict:
        return {"x-client-id": self.client_id} if self.client_id else {}

    @staticmethod
    def _json(request: httpx.Request, status: int, body: Any, ndjson: bool = False) -> httpx.Response:
        content = (json.dumps(body) + "\n") if ndjson else json.dumps(body)
        return httpx.Response(status, request=request, content=content.encode(),
                              headers={"Content-Type": "application/x-ndjson" if ndjson else "application/json"})

    # -- routes -------------------------------------------------------------
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        try:
            if path == "/api/version":
                health = self._http.get(self.base + "/v1/health").json()
                status = 200 if health.get("serving") else 503
                return self._json(request, status, {"version": "cordon"})
            if path == "/api/tags":
                return self._tags(request)
            if path == "/api/show":
                return self._json(request, 200, {
                    "capabilities": ["completion", "tools"],
                    "model_info": {"general.context_length": self.num_ctx},
                    "details": {"family": "cordon", "parameter_size": ""},
                })
            if path == "/api/chat":
                return self._chat(request)
        except httpx.HTTPError as e:
            return self._json(request, 502, {"error": f"Could not reach Cordon at {self.base}: {e}"})
        return self._json(request, 404, {"error": f"{path} is not served through Cordon"})

    def _tags(self, request: httpx.Request) -> httpx.Response:
        r = self._http.get(self.base + "/openai/v1/models", headers=self._headers())
        if r.status_code >= 400:
            return self._json(request, r.status_code, {"error": r.text[:300]})
        names = [m.get("id") for m in r.json().get("data", []) if m.get("id")]
        if self.model not in names:
            names.insert(0, self.model)
        return self._json(request, 200, {"models": [
            {"name": n, "model": n, "capabilities": ["completion", "tools"],
             "details": {"family": "cordon", "parameter_size": ""}} for n in names]})

    def _chat(self, request: httpx.Request) -> httpx.Response:
        global _last_receipt
        payload = json.loads(request.content or b"{}")
        options = payload.get("options") or {}
        num_predict = options.get("num_predict")
        max_tokens = self.max_tokens if not num_predict or num_predict < 0 else min(int(num_predict), self.max_tokens)
        body: dict[str, Any] = {
            "model": payload.get("model") or self.model,
            "messages": _to_openai_messages(payload.get("messages", [])),
            "max_tokens": max_tokens,
            "stream": False,
        }
        if "temperature" in options:
            body["temperature"] = options["temperature"]
        if payload.get("tools"):
            body["tools"] = payload["tools"]
        if payload.get("format") == "json":
            body["response_format"] = {"type": "json_object"}

        r = self._http.post(self.base + "/openai/v1/chat/completions", json=body, headers=self._headers())
        if r.status_code >= 400:
            try:
                err = (r.json() or {}).get("error") or {}
                message = err.get("message") or r.text[:300]
            except ValueError:
                message = r.text[:300]
            return self._json(request, r.status_code, {"error": f"Cordon: {message}"})

        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        usage = data.get("usage") or {}
        finish = choice.get("finish_reason") or "stop"
        cordon = data.get("cordon")
        if cordon:
            with _receipt_lock:
                _last_receipt = cordon
        out = {
            "model": data.get("model") or body["model"],
            "message": {
                "role": "assistant",
                "content": msg.get("content") or "",
                **({"tool_calls": _from_openai_tool_calls(msg.get("tool_calls"))} if msg.get("tool_calls") else {}),
            },
            "done": True,
            "done_reason": "length" if finish == "length" else "stop",
            "prompt_eval_count": usage.get("prompt_tokens", 0),
            "eval_count": usage.get("completion_tokens", 0),
            **({"cordon": cordon} if cordon else {}),
        }
        return self._json(request, 200, out, ndjson=bool(payload.get("stream")))


def cordon_client(settings) -> httpx.Client:
    """An httpx client for OllamaEngine whose every request goes to Cordon."""
    cert = None
    if getattr(settings, "cordon_client_cert", None):
        cert = (settings.cordon_client_cert, settings.cordon_client_key or "")
    transport = CordonTransport(
        base_url=settings.cordon_url,
        client_id=settings.cordon_client_id,
        model=settings.cordon_model,
        num_ctx=settings.cordon_num_ctx,
        max_tokens=settings.cordon_max_tokens,
        timeout=float(settings.ollama_request_timeout),
        cert=cert,
        verify=getattr(settings, "cordon_ca_cert", None) or True,
    )
    return httpx.Client(base_url="http://cordon.bridge", transport=transport,
                        timeout=float(settings.ollama_request_timeout))
