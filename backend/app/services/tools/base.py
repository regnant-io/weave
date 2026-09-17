"""Tool registry primitives."""
from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Callable


def _schema_errors(value: Any, schema: dict, path: str = "input") -> list[str]:
    """Validate the useful JSON-Schema subset used by Weave tools.

    Provider-side schema handling is advisory. Model output is untrusted and
    must satisfy the contract again at the execution boundary. Keeping this
    small avoids a large runtime dependency while covering every schema feature
    currently emitted by the registry.
    """
    errors: list[str] = []
    expected = schema.get("type")
    types = {
        "object": dict, "array": list, "string": str,
        "number": (int, float), "integer": int, "boolean": bool,
    }
    if expected in types:
        valid = isinstance(value, types[expected])
        if expected in {"number", "integer"} and isinstance(value, bool):
            valid = False
        if not valid:
            return [f"{path} must be {expected}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path} must be one of {schema['enum']!r}")
    if isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)):
            errors.append(f"{path} is too short")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            errors.append(f"{path} is too long")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path} is below the minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path} exceeds the maximum")
    if isinstance(value, list):
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            errors.append(f"{path} has too many items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(_schema_errors(item, item_schema, f"{path}[{index}]"))
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for required in schema.get("required", []):
            if required not in value:
                errors.append(f"{path}.{required} is required")
        if schema.get("additionalProperties") is False:
            for key in value.keys() - props.keys():
                errors.append(f"{path}.{key} is not allowed")
        for key, item in value.items():
            if key in props:
                errors.extend(_schema_errors(item, props[key], f"{path}.{key}"))
    return errors

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
    #: Exact capability names advertised for this turn.  Model tool calls are
    #: untrusted input too: a provider can return a name that was never present
    #: in its schema.  Keeping the allowlist in the execution context makes the
    #: trust/service/intent decision hold at the point of use.
    allowed_tools: frozenset[str] | None = None

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
        trust_level = TRUST_ORDER.get(trust, 0)
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
            return {"status": "error", "code": "unknown_tool",
                    "error": f"unknown tool {name!r}", "retryable": False}
        if ctx.allowed_tools is not None and name not in ctx.allowed_tools:
            return {
                "status": "rejected",
                "code": "tool_not_allowed",
                "error": f"tool {name!r} is not available on this turn",
                "retryable": False,
            }
        trust_level = TRUST_ORDER.get(ctx.trust, 0)
        if trust_level < TRUST_ORDER.get(tool.trust_required, 0):
            return {"status": "rejected", "code": "insufficient_trust",
                    "error": "insufficient trust for this tool", "retryable": False}
        if any(ctx.services.get(service) is None for service in tool.requires_services):
            return {"status": "unavailable", "code": "service_unavailable",
                    "error": "required service is unavailable", "retryable": True}
        mode = getattr(ctx.project, "mode", None)
        if mode is not None and mode not in tool.modes:
            return {"status": "rejected", "code": "mode_not_allowed",
                    "error": "tool is unavailable in this mode", "retryable": False}
        if not isinstance(tool_input, dict):
            return {"status": "error", "code": "invalid_tool_input",
                    "error": "tool input must be an object", "retryable": True}
        cleaned = dict(tool_input)
        cleaned.pop("note", None)
        validation_schema = {
            **tool.input_schema,
            "properties": tool.input_schema.get("properties", {}),
        }
        errors = _schema_errors(cleaned, validation_schema)
        if errors:
            return {"status": "error", "code": "invalid_tool_input",
                    "error": "; ".join(errors[:8]), "details": errors[:8],
                    "retryable": True}
        try:
            started = time.monotonic()
            result = tool.execute(ctx, cleaned)
            from ...metrics import observe
            observe("tool", name, str(result.get("status", "ok")),
                    (time.monotonic() - started) * 1000)
            return result
        except Exception as exc:  # noqa: BLE001 - a tool failure must not crash the turn
            from ...metrics import observe
            observe("tool", name, "exception", (time.monotonic() - started) * 1000)
            return {"status": "error", "code": "tool_execution_failed",
                    "error": f"{type(exc).__name__}: {exc}", "retryable": True}


_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        from . import builtin  # noqa: F401 - registers the built-in tools
        builtin.register_all(_registry)
    return _registry
