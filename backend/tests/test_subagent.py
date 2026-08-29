"""Delegation: scope, bounds, and what comes back.

These are the properties that make delegation safe to leave switched on. The
interesting ones are all negative — what a delegate CANNOT do — because the
value of the restriction is entirely in it holding when nobody is looking.
"""
from __future__ import annotations

from app.services.orchestration import subagent


class _Engine:
    """A stand-in engine that records the toolset it was handed."""

    name = "fake"
    available = True
    streams = True

    def __init__(self, reply: str = "The figure is 61%.", calls=None):
        self.reply = reply
        self.calls = calls if calls is not None else []
        self.seen_tools: list[list[str]] = []

    def generate(self, *, system, messages, tools, tool_executor, tier, **kw):
        from app.services.orchestration.llm import TurnResult

        self.seen_tools.append([t["name"] for t in tools])
        events = []
        for name, args in self.calls:
            events.append({"name": name, "input": args,
                           "result": tool_executor(name, args)})
        return TurnResult(text=self.reply, tool_events=events, tier_used=tier)


def _tools(*names):
    return [{"name": n, "description": n, "input_schema": {"type": "object"}} for n in names]


def test_delegate_only_gets_read_only_tools():
    """The restriction is enforced by the RUNNER, not asked for in the prompt.

    Filtering at the call site would mean the next caller has to remember to do
    it, and a delegate handed `workspace_write` is one prompt-injected page away
    from writing a file nobody asked for.
    """
    engine = _Engine()
    out = subagent.run_delegate(
        engine=engine,
        tools=_tools("web_search", "workspace_write", "run_analysis",
                     "create_3d_experience", "delegate", "workspace_read"),
        tool_executor=lambda n, a: {"status": "ok"},
        emit=lambda k, d: None,
        task="What is rural water coverage in Dodoma?",
    )
    assert out["status"] == "ok"
    offered = set(engine.seen_tools[0])
    assert offered == {"web_search", "workspace_read"}
    # The one that matters most: a delegate cannot spawn a delegate.
    assert "delegate" not in offered


def test_delegate_reports_its_finding_and_its_sources():
    engine = _Engine(
        reply="Coverage was 61% in 2022.",
        calls=[("web_search", {"query": "dodoma water"})],
    )

    def executor(name, args):
        return {"status": "ok", "results": [
            {"url": "https://nbs.go.tz/a", "title": "A"},
            {"url": "https://nbs.go.tz/b", "title": "B"},
        ]}

    out = subagent.run_delegate(
        engine=engine, tools=_tools("web_search"), tool_executor=executor,
        emit=lambda k, d: None, task="coverage?",
    )
    assert out["report"].startswith("Coverage was 61%")
    assert out["sources"] == ["https://nbs.go.tz/a", "https://nbs.go.tz/b"]
    assert out["tool_calls"] == 1


def test_delegate_without_research_tools_is_unavailable_not_hallucinating():
    """No tools means no lookup, and a model call with no lookup is just the
    model's recollection presented as a finding. Refusing is the honest result."""
    out = subagent.run_delegate(
        engine=_Engine(), tools=_tools("create_diagram", "canvas_write"),
        tool_executor=lambda n, a: {}, emit=lambda k, d: None, task="anything",
    )
    assert out["status"] == "unavailable"


def test_delegate_prose_is_not_streamed_into_the_transcript():
    """A delegate's working notes are addressed to the caller, not the user.

    Streaming them would put a second voice in the middle of the answer. Its
    STEP activity still shows, because a silent minute reads as a hang.
    """
    seen: list[str] = []

    class Chatty(_Engine):
        def generate(self, *, system, messages, tools, tool_executor, tier,
                     on_event=None, **kw):
            from app.services.orchestration.llm import TurnResult

            self.seen_tools.append([t["name"] for t in tools])
            if on_event:
                on_event("token", {"text": "thinking out loud"})
                on_event("step_start", {"id": "s1", "tool": "web_search"})
            return TurnResult(text="done", tool_events=[], tier_used=tier)

    subagent.run_delegate(
        engine=Chatty(), tools=_tools("web_search"),
        tool_executor=lambda n, a: {}, emit=lambda k, d: seen.append(k),
        task="x",
    )
    assert "token" not in seen
    assert "step_start" in seen


def test_empty_task_is_rejected_before_a_model_call():
    out = subagent.run_delegate(
        engine=_Engine(), tools=_tools("web_search"),
        tool_executor=lambda n, a: {}, emit=lambda k, d: None, task="   ",
    )
    assert out["status"] == "error"


def test_report_is_capped():
    """The whole point is keeping the sources out of the caller's window; a
    delegate that returns everything it read has defeated it."""
    engine = _Engine(reply="x" * (subagent.MAX_REPORT_CHARS + 500))
    out = subagent.run_delegate(
        engine=engine, tools=_tools("web_search"),
        tool_executor=lambda n, a: {}, emit=lambda k, d: None, task="x",
    )
    assert len(out["report"]) == subagent.MAX_REPORT_CHARS
    assert out["truncated"] is True
