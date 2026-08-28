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

# `output_fraction` is the share of the model's REAL context window this level is
# allowed to spend on its own output; `floor`/`cap` bound that in absolute tokens
# (cap 0 = unbounded). Fixed num_predict values were the reason a long file
# generation stopped mid-line: a 2048-token ceiling truncates any substantial
# file regardless of how much window the model actually has.
EFFORT_SPEC = {
    "spool": {
        "label": "Spool",
        "output_fraction": 0.10,
        "floor": 1024,
        "cap": 4096,
        "think": False,
        "prompt": ("EFFORT: Spool (quick). Answer concisely and directly. Prefer a "
                   "short answer; use tools only if clearly necessary."),
    },
    "weave": {
        "label": "Weave",
        "output_fraction": 0.35,
        "floor": 4096,
        "cap": 0,
        "think": False,
        "prompt": ("EFFORT: Weave (balanced). Give a complete, well-structured answer. "
                   "Use tools (analysis, retrieval, web) when they improve accuracy. "
                   "Never truncate a file or a code block to save space — finish it."),
    },
    "tapestry": {
        "label": "Tapestry",
        "output_fraction": 1.0,
        "floor": 8192,
        "cap": 0,
        "think": True,
        "prompt": ("EFFORT: Tapestry (deep). Be thorough and rigorous. Plan, use tools "
                   "liberally (research the web, run analysis, verify), and produce a "
                   "comprehensive, well-cited answer. Take the time you need. Write "
                   "complete files — never abbreviate with '...' or 'rest unchanged'."),
    },
}


def effort_spec(effort: str | None) -> dict:
    return EFFORT_SPEC.get((effort or DEFAULT_EFFORT).lower(), EFFORT_SPEC[DEFAULT_EFFORT])


#: Share of the window handed to the model's own output at the deepest level.
#: Generous enough that nothing real is ever truncated, while leaving room for
#: the prompt and history.
UNBOUNDED_FRACTION = 0.75


def num_predict_for(effort: str | None, context_window: int) -> int:
    """Output-token budget for one step, derived from the model's REAL window.

    ALWAYS POSITIVE.

    This used to return -1 at the deepest level, which is how a local Ollama
    spells "generate until you decide to stop". A hosted `:cloud` model proxies
    to an OpenAI-shaped API and rejects it outright:

        400 {"error": "max_tokens must be positive, got: -1"}

    So every Tapestry turn on a cloud model 400'd and fell through to the
    deterministic offline engine — the deepest, slowest, most expensive setting
    was reliably producing the worst answer in the product, and the only symptom
    was that thorough mode felt oddly shallow.

    A large positive budget gets what -1 was reaching for. The original bug it
    was introduced to fix was a FIXED 2048-token ceiling truncating long files;
    three quarters of a 131k window is 98k tokens, which is not a ceiling anyone
    will meet.
    """
    spec = effort_spec(effort)
    ctx = max(1, int(context_window or 0))
    if spec["output_fraction"] >= 1.0:
        return max(int(spec["floor"]), int(ctx * UNBOUNDED_FRACTION))
    budget = int(ctx * float(spec["output_fraction"]))
    budget = max(int(spec["floor"]), budget)
    cap = int(spec["cap"] or 0)
    if cap > 0:
        budget = min(budget, cap)
    return budget


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
