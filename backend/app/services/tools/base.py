"""Tool registry primitives."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

# trust ordering: anonymous < verified < institutional
TRUST_ORDER = {"anonymous": 0, "verified": 1, "institutional": 2}


@dataclass
class ToolContext:
    """Everything a tool needs to run, assembled per turn by the orchestrator.

    Tools never reach into global state — they read from the context, which keeps
    them testable and keeps the security boundary explicit.
    """
    db: Any = None
    project: Any = None
    dataset: Any = None
    message_id: str | None = None
    language: str = "sw"
    trust: str = "verified"
    services: dict[str, Any] = field(default_factory=dict)   # analysis, retrieval, ...
    emit: Callable[[str, dict], None] | None = None          # progress sink (SSE stages)
    #: The conversation this turn belongs to. Tools that write memory record
    #: where a fact came from; tools that ask the user need somewhere to anchor.
    thread: Any = None
    #: threading.Event set when the client disconnects. A tool that waits on
    #: anything (a user answer, a long build) must check this or it will keep a
    #: worker thread alive after the user has already walked away.
    cancel: Any = None

    def progress(self, event: str, data: dict) -> None:
        if self.emit:
            self.emit(event, data)

    def cancelled(self) -> bool:
        return self.cancel is not None and self.cancel.is_set()


ToolExecute = Callable[[ToolContext, dict], dict]


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    execute: ToolExecute
    trust_required: str = "anonymous"
    modes: tuple[str, ...] = ("student", "researcher")
    # If a required service isn't wired for this run, the tool is hidden rather
    # than advertised-and-broken.
    requires_services: tuple[str, ...] = ()
    # Router intents this tool is offered for (empty = all). Keeps the model from
    # e.g. web-searching a concept explanation.
    intents: tuple[str, ...] = ()
    #: May this tool run CONCURRENTLY with other calls in the same model turn?
    #:
    #: Models routinely ask for several independent reads at once -- three web
    #: searches, four files -- and running them one after another makes a turn
    #: take as long as the sum of its slowest parts for no reason. Concurrency is
    #: opt-in per tool rather than global because two things make it unsafe:
    #:
    #:   * TOUCHING THE DATABASE. `ctx.db` is one SQLAlchemy Session, and a
    #:     Session is explicitly not thread-safe. Anything reading or writing
    #:     through it (analysis, library search, canvas, memory) stays serial.
    #:   * CHANGING THE WORLD. Two writes to the same workspace path, or two
    #:     renders of the same artifact, have an order that matters and a result
    #:     that depends on it. Only reads are marked safe.
    #:
    #: The default is False: a new tool is serial until someone has thought
    #: about it, which is the right way round for a correctness property.
    parallel_safe: bool = False

    #: Present-tense label the model writes for the UI step chip. Declared on
    #: every tool so the model can narrate its own work; stripped by the
    #: orchestrator before execute() ever sees it. Optional by design — when it
    #: is missing the client derives a title from the tool and its arguments,
    #: so a small local model that ignores the field costs us nothing.
    NOTE_PROPERTY = {
        "note": {
            "type": "string",
            "description": (
                "A short present-tense label (under 8 words) describing what you are "
                "doing and why, shown to the user as a progress step. "
                "Example: 'Checking whether the 2022 census is online'."
            ),
        },
    }

    def schema(self) -> dict:
        props = {**self.input_schema.get("properties", {}), **self.NOTE_PROPERTY}
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {**self.input_schema, "properties": props},
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def available(self, *, mode: str, trust: str, services: dict[str, Any],
                  intent: str | None = None,
                  force: set[str] | None = None) -> list[Tool]:
        """Tools usable in this (mode, trust, intent) with the services wired.

        `force` names tools the user explicitly enabled in the composer. Intent
        gating is a heuristic about what the user probably wants; an explicit
        toggle is a statement of what they actually want, so it wins. Trust and
        service-availability checks are NOT bypassed — those are real
        constraints, not guesses.
        """
        out = []
        forced = force or set()
        trust_level = TRUST_ORDER.get(trust, 1)
        for t in self._tools.values():
            if mode not in t.modes:
                continue
            if trust_level < TRUST_ORDER.get(t.trust_required, 0):
                continue
            if any(s not in services or services[s] is None for s in t.requires_services):
                continue
            if t.intents and intent is not None and intent not in t.intents and t.name not in forced:
                continue
            out.append(t)
        return out

    def parallel_safe_names(self) -> set[str]:
        """Names of tools that may run concurrently with each other."""
        return {t.name for t in self._tools.values() if t.parallel_safe}

    def schemas(self, *, mode: str, trust: str, services: dict[str, Any],
                intent: str | None = None, force: set[str] | None = None) -> list[dict]:
        return [t.schema() for t in self.available(mode=mode, trust=trust, services=services,
                                                   intent=intent, force=force)]

    def execute(self, name: str, ctx: ToolContext, tool_input: dict) -> dict:
        tool = self.get(name)
        if tool is None:
            return {"status": "error", "error": f"unknown tool {name!r}"}
        try:
            return tool.execute(ctx, tool_input or {})
        except Exception as exc:  # noqa: BLE001 - a tool failure must not crash the turn
            return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        from . import builtin  # noqa: F401 - registers the built-in tools
        builtin.register_all(_registry)
    return _registry
