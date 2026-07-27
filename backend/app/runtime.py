"""Runtime-mutable configuration (overrides the static Settings at request time).

Lets the Settings page change the Ollama host/model and default effort without a
restart. Changing the host/model resets the cached LLM engine so the next call
uses the new endpoint.
"""
from __future__ import annotations

from .config import settings

_overrides: dict = {}

# --- effort ("Loom") levels: unique, on-brand terminology ------------------
# Spool  = quick/low   | Weave = balanced/mid | Tapestry = deep/high
EFFORT_LEVELS = ("spool", "weave", "tapestry")
DEFAULT_EFFORT = "weave"

EFFORT_SPEC = {
    "spool": {
        "label": "Spool",
        "num_predict": 700,
        "think": False,
        "prompt": ("EFFORT: Spool (quick). Answer concisely and directly. Prefer a "
                   "short answer; use tools only if clearly necessary."),
    },
    "weave": {
        "label": "Weave",
        "num_predict": 2048,
        "think": False,
        "prompt": ("EFFORT: Weave (balanced). Give a complete, well-structured answer. "
                   "Use tools (analysis, retrieval, web) when they improve accuracy."),
    },
    "tapestry": {
        "label": "Tapestry",
        "num_predict": 4096,
        "think": True,
        "prompt": ("EFFORT: Tapestry (deep). Be thorough and rigorous. Plan, use tools "
                   "liberally (research the web, run analysis, verify), and produce a "
                   "comprehensive, well-cited answer. Take the time you need."),
    },
}


def effort_spec(effort: str | None) -> dict:
    return EFFORT_SPEC.get((effort or DEFAULT_EFFORT).lower(), EFFORT_SPEC[DEFAULT_EFFORT])


def ollama_host() -> str:
    return _overrides.get("ollama_host") or settings.ollama_host


def ollama_model() -> str:
    return _overrides.get("ollama_model") or settings.ollama_model


def set_ollama(host: str | None = None, model: str | None = None) -> None:
    changed = False
    if host is not None and host.strip():
        _overrides["ollama_host"] = host.strip()
        changed = True
    if model is not None and model.strip():
        _overrides["ollama_model"] = model.strip()
        changed = True
    if changed:
        from .services.orchestration.llm import reset_engine
        reset_engine()


def current() -> dict:
    return {"ollama_host": ollama_host(), "ollama_model": ollama_model()}
