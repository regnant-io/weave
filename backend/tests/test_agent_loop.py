"""The supervised loop, the artifact gate, and model resolution.

These are the three pieces that decide whether Weave does the work or only
appears to, so they are tested against the failures that actually happened
rather than against their happy paths:

  * models emit malformed plan payloads, and a plan discarded over its packaging
    is a turn that runs unsupervised;
  * a broken artifact must come back to the model as a FAILED tool call, because
    a model told `status: ok` has been told its work is finished;
  * a configured model that does not exist must be substituted loudly, not
    retried into a silent offline fallback.

No network, no Docker, no LLM: every seam is a stub, so these run in CI.
"""
from __future__ import annotations

import pytest

from app.services.orchestration import agent as ag
from app.services.orchestration.verification import MAX_REPAIRS, ArtifactGate, Verdict


# --------------------------------------------------------------------------- #
#  Plan parsing: what models really send                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # The documented shape.
        (["Build it", "Open it"], ["Build it", "Open it"]),
        # gpt-oss:20b returns objects even when `items` says string.
        ([{"title": "Build it", "done_when": "it renders"}], ["Build it — it renders"]),
        # ...and sometimes uses a different key entirely.
        ([{"step": "Build it"}, {"text": "Open it"}], ["Build it", "Open it"]),
        # A single newline-joined string instead of a list.
        ("1. Build it\n2. Open it", ["Build it", "Open it"]),
        # JSON that was serialised twice.
        ('["Build it", "Open it"]', ["Build it", "Open it"]),
        # Numbering the model wrote into the text, which the renderer adds too.
        (["1) Build it", "2. Open it"], ["Build it", "Open it"]),
        (None, []),
        ([], []),
    ],
)
def test_plan_steps_survive_every_shape_models_emit(raw, expected):
    """A plan must not be lost because of how it was packaged.

    Every one of these shapes was produced by a model this product runs on,
    given a schema that asked for a list of strings.
    """
    assert ag._string_list(raw) == expected


def test_plan_renders_surface_and_status():
    plan = ag.Plan(
        goal="A flyable solar system",
        surface="artifact",
        steps=[ag.PlanStep(1, "Build the scene"),
               ag.PlanStep(2, "Open it", status="done", note="renders clean")],
        checks=["planets orbit at the right relative rates"],
    )
    text = plan.render()
    assert "delivering as: artifact" in text
    assert "[ ] 1. Build the scene" in text
    assert "[x] 2. Open it" in text
    assert "renders clean" in text
    assert "planets orbit" in text


# --------------------------------------------------------------------------- #
#  Policy                                                                      #
# --------------------------------------------------------------------------- #
def test_quick_effort_skips_the_ceremony():
    """A one-line question must not pay for planning and review."""
    p = ag.LoopPolicy.for_effort("spool", complex_request=True)
    assert not p.plan and not p.review


def test_chat_is_not_planned_but_building_is():
    assert not ag.LoopPolicy.for_effort("weave", complex_request=False).plan
    assert ag.LoopPolicy.for_effort("weave", complex_request=True).plan
    # Deep effort always supervises, and allows more rounds.
    deep = ag.LoopPolicy.for_effort("tapestry", complex_request=False)
    assert deep.plan and deep.review and deep.max_continuations >= 5


@pytest.mark.parametrize(
    ("text", "is_work"),
    [
        ("hi", False),
        ("what does BAKITA mean?", False),
        ("build me a 3d solar system", True),
        ("tengeneza grafu ya mvua", True),
        ("analyse this dataset for me", True),
        ("x" * 260, True),
    ],
)
def test_work_detection(text, is_work):
    assert ag.looks_like_work(text) is is_work


# --------------------------------------------------------------------------- #
#  The supervisor's opinion about "finished"                                   #
# --------------------------------------------------------------------------- #
class _Engine:
    """An engine that returns canned text and optionally calls tools."""

    name = "stub"

    def __init__(self, script):
        #: one entry per generate() call: (text, [(tool, args), ...])
        self.script = list(script)
        self.calls = 0
        self.systems: list[str] = []
        self.tools_offered: list[list[str]] = []

    def generate(self, *, system, messages, tools, tool_executor, tier, **kw):
        self.systems.append(system)
        self.tools_offered.append([t["name"] for t in tools])
        text, calls = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        for name, args in calls:
            tool_executor(name, args)
        return ag.AgentResult(text=text) if False else _Turn(text)


class _Turn:
    def __init__(self, text):
        self.text = text
        self.tool_events = []
        self.tier_used = "fast"


def _agent(engine, policy, **kw):
    return ag.Agent(
        engine=engine, system="SYS", messages=[{"role": "user", "content": "do it"}],
        tools=[{"name": "workspace_write"}, {"name": "create_simulation"}],
        tool_executor=kw.pop("tool_executor", lambda n, a: {"status": "ok"}),
        emit=kw.pop("emit", lambda e, d: None),
        policy=policy, user_text="build me a thing", **kw,
    )


def test_open_plan_steps_bring_the_model_back():
    """Going quiet with the plan unfinished is not 'done'."""
    engine = _Engine([("first pass", [("workspace_write", {})]),
                      ("second pass", [("workspace_write", {})])])
    a = _agent(engine, ag.LoopPolicy(plan=False, review=False, max_continuations=2))
    a.plan = ag.Plan(goal="g", steps=[ag.PlanStep(1, "unfinished")])
    a.run()
    assert engine.calls >= 2, "the model was allowed to stop with an open plan step"


def test_the_loop_gives_up_when_nothing_is_advancing():
    """A pass that changes nothing must end the turn, not buy another pass.

    Otherwise an open plan step the model will never close costs the user the
    whole continuation budget, one slow model call at a time.
    """
    engine = _Engine([("", [])])          # no text, no tools, no plan movement
    a = _agent(engine, ag.LoopPolicy(plan=False, review=False, max_continuations=5))
    a.plan = ag.Plan(goal="g", steps=[ag.PlanStep(1, "never closed")])
    result = a.run()
    assert result.stopped_because == "stalled"
    assert engine.calls <= 2


def test_pressing_on_open_steps_is_bounded():
    """Press twice, then stop nagging.

    A model doing the work but not ticking boxes looks identical to one that
    abandoned the task; nagging it forever burns the budget re-doing work.
    """
    engine = _Engine([("working", [("workspace_write", {})])] * 6)
    a = _agent(engine, ag.LoopPolicy(plan=False, review=False, max_continuations=5))
    a.plan = ag.Plan(goal="g", steps=[ag.PlanStep(1, "never closed")])
    a.run()
    assert a._plan_nags == 2


def test_an_unrepaired_artifact_is_a_gap():
    """A model that absorbed a repair request and moved on must be sent back."""
    engine = _Engine([("all done!", [])])
    a = _agent(engine, ag.LoopPolicy(plan=False, review=False, max_continuations=1))
    a.tool_events = [{
        "name": "create_simulation", "input": {},
        "result": {"status": "needs_repair",
                   "verification": {"errors": ["the page rendered nothing"]}},
    }]
    gaps = a._gaps()
    assert any("never fixed" in g for g in gaps)


def test_a_repaired_artifact_is_not_a_gap():
    engine = _Engine([("done", [])])
    a = _agent(engine, ag.LoopPolicy(plan=False, review=False))
    a.tool_events = [
        {"name": "create_simulation", "input": {}, "result": {"status": "needs_repair"}},
        {"name": "create_simulation", "input": {}, "result": {"status": "ok"}},
    ]
    assert a._gaps() == []


# --------------------------------------------------------------------------- #
#  Surface enforcement                                                         #
# --------------------------------------------------------------------------- #
def test_artifact_surface_removes_the_workspace_authoring_tools():
    """The wrong instrument is taken off the tray, not merely discouraged.

    Prompt wording did not stop 'build me an interactive 3D scene' from becoming
    an index.html and an HTTP server. Twice.
    """
    a = _agent(_Engine([("", [])]), ag.LoopPolicy(plan=False, review=False))
    a.plan = ag.Plan(goal="g", surface="artifact", steps=[ag.PlanStep(1, "build")])
    offered = {t["name"] for t in a._tools_with_loop_control()}
    assert "workspace_write" not in offered
    assert "create_simulation" in offered
    # Re-planning stays possible, so a wrong surface is recoverable.
    assert "submit_plan" in offered


def test_workspace_surface_keeps_its_tools():
    a = _agent(_Engine([("", [])]), ag.LoopPolicy(plan=False, review=False))
    a.plan = ag.Plan(goal="g", surface="workspace", steps=[ag.PlanStep(1, "build")])
    offered = {t["name"] for t in a._tools_with_loop_control()}
    assert "workspace_write" in offered


def test_the_surface_directive_reaches_the_model():
    a = _agent(_Engine([("", [])]), ag.LoopPolicy(plan=False, review=False))
    a.plan = ag.Plan(goal="g", surface="artifact", steps=[ag.PlanStep(1, "build")])
    assert "SURFACE: ARTIFACT" in a._system_with_plan()


def test_plan_updates_move_the_ledger():
    a = _agent(_Engine([("", [])]), ag.LoopPolicy(plan=False, review=False))
    a.plan = ag.Plan(goal="g", steps=[ag.PlanStep(1, "one"), ag.PlanStep(2, "two")])
    assert a._apply_plan_update({"step": 1, "status": "done"})["remaining_steps"] == 1
    assert a.plan.get(1).status == "done"
    # A step number that does not exist is reported, not silently ignored.
    assert a._apply_plan_update({"step": 9, "status": "done"})["status"] == "error"


# --------------------------------------------------------------------------- #
#  The artifact gate                                                           #
# --------------------------------------------------------------------------- #
def test_a_broken_artifact_comes_back_as_a_failed_tool_call():
    """The load-bearing behaviour of the whole gate.

    A model handed `{"status": "ok"}` has been told the work is finished, and no
    amount of system-prompt exhortation reliably overrides a tool result.
    """
    verdict = Verdict(checked=True, ok=False, attempt=1,
                      errors=["Scene error: createScene did not return a BABYLON.Scene"])
    out = ArtifactGate.apply({"status": "ok", "output_files": [{"s3_key": "k"}]},
                             verdict, "create_3d_experience")
    assert out["status"] == "needs_repair"
    assert out["verified"] is False
    # Nothing was released, so the result must not imply otherwise.
    assert "output_files" not in out
    assert "createScene did not return" in out["error"]
    assert "call `create_3d_experience` again" in out["error"]
    # The specific hint for this failure mode.
    assert "return scene;" in out["error"]


def test_a_verified_artifact_passes_through():
    verdict = Verdict(checked=True, ok=True, attempt=1)
    out = ArtifactGate.apply({"status": "ok", "output_files": [{"s3_key": "k"}]},
                             verdict, "create_simulation")
    assert out["status"] == "ok"
    assert out["verified"] is True
    assert out["output_files"]


def test_after_the_budget_it_ships_with_the_defects_on_record():
    """Released, but the model is told not to call it working."""
    verdict = Verdict(checked=True, ok=False, attempt=MAX_REPAIRS, exhausted=True,
                      errors=["the page rendered nothing at all"])
    out = ArtifactGate.apply({"status": "ok", "output_files": [{"s3_key": "k"}]},
                             verdict, "create_html_page")
    assert out["status"] == "ok"
    assert out["verified"] is False
    assert out["output_files"], "an exhausted artifact is still shown to the user"
    assert "KNOWN DEFECTS" in out["note"]
    assert "Do NOT describe it as finished" in out["note"]


def test_the_repair_budget_is_per_artifact_not_per_turn():
    gate = ArtifactGate("proj")
    a = {"visual_id": "v1"}
    b = {"visual_id": "v2"}
    assert gate._identity("create_diagram", a, {}) != gate._identity("create_diagram", b, {})
    # The same visual retried counts against one budget.
    assert (gate._identity("create_diagram", a, {})
            == gate._identity("create_diagram", {}, {"visual_id": "v1"}))


def test_only_page_producing_tools_are_gated():
    gate = ArtifactGate("proj")
    assert gate.gates("create_3d_experience")
    assert gate.gates("create_html_page")
    # A Vega chart is rendered to SVG server-side: there is no page and no
    # script, so a browser can tell us nothing the renderer did not.
    assert not gate.gates("generate_visual")
    assert not gate.gates("run_analysis")


def test_a_tool_that_failed_before_rendering_is_not_probed():
    gate = ArtifactGate("proj")
    verdict = gate.check("create_diagram", {}, {"status": "error", "error": "bad spec"})
    assert verdict.checked is False


# --------------------------------------------------------------------------- #
#  Model resolution                                                            #
# --------------------------------------------------------------------------- #
class _FakeOllama:
    """OllamaEngine with its HTTP layer replaced by a fixed model listing."""

    def __init__(self, models):
        from app.services.orchestration.llm import OllamaEngine

        self.engine = OllamaEngine.__new__(OllamaEngine)
        self.engine._tags_cache = (10**9, models)   # never expires during a test
        self.engine._client = None
        self.engine._httpx = None


_CLOUD = [
    {"name": "gpt-oss:120b-cloud", "details": {"parameter_size": "117B"},
     "capabilities": ["completion", "tools", "thinking"]},
    {"name": "gemma4:cloud", "details": {"parameter_size": "32.7B"},
     "capabilities": ["completion", "thinking", "tools", "vision"]},
    {"name": "minimax-m3:cloud", "details": {"parameter_size": "0"},
     "capabilities": ["completion", "tools", "thinking", "vision"]},
    {"name": "smollm:135m", "details": {"parameter_size": "134.52M"},
     "capabilities": ["completion"]},
]


def test_a_model_that_is_not_installed_is_substituted():
    """The bug: .env named a model the server had never pulled.

    Every turn then made retried calls to a 404 and answered from the offline
    engine, while /health reported the Ollama engine as healthy.
    """
    e = _FakeOllama(_CLOUD).engine
    assert e.resolve_model("llama3.2:3b") == "gpt-oss:120b-cloud"


def test_a_model_that_is_installed_is_honoured():
    e = _FakeOllama(_CLOUD).engine
    assert e.resolve_model("gemma4:cloud") == "gemma4:cloud"


def test_models_without_tool_support_are_never_chosen_automatically():
    """A model that cannot call tools turns Weave back into a chat window."""
    e = _FakeOllama([_CLOUD[3]] + [_CLOUD[0]]).engine
    assert e.resolve_model("nope") == "gpt-oss:120b-cloud"
    assert e.supports_tools("smollm:135m") is False


def test_cloud_tags_are_classified_large():
    """The old name-regex looked for a parameter count in the tag.

    `minimax-m3:cloud` and `gemma4:cloud` contain none, so both were treated as
    small local models and handed the cut-down prompt meant for a 3B.
    """
    e = _FakeOllama(_CLOUD).engine
    assert e.model_class("minimax-m3:cloud") == "large"
    assert e.model_class("gemma4:cloud") == "large"
    assert e.model_class("gpt-oss:120b-cloud") == "large"
    assert e.model_class("smollm:135m") == "small"


# --------------------------------------------------------------------------- #
#  Rate limit vs. quota — the same status code, different remedies             #
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, text):
        self.text = text
        self.headers = {}


def test_a_session_limit_is_recognised_as_quota_not_backpressure():
    """Ollama Cloud's real body when a free account runs out.

    A burst limit clears in seconds so backing off is right; a session limit
    does not clear at all, so backing off spends 45 seconds arriving at the
    same failure and then silently degrades the answer.
    """
    from app.services.orchestration.llm import OllamaEngine

    body = ('{"error":"you (someone) have reached your session usage limit, '
            'upgrade for higher limits: https://ollama.com/upgrade"}')
    msg = OllamaEngine._quota_message(_Resp(body))
    assert "session usage limit" in msg
    # The provider's own words survive: they name the account and the fix.
    assert "ollama.com/upgrade" in msg


def test_plain_backpressure_is_not_treated_as_quota():
    from app.services.orchestration.llm import OllamaEngine

    assert OllamaEngine._quota_message(_Resp('{"error":"too many requests"}')) == ""
    assert OllamaEngine._quota_message(_Resp("")) == ""


# --------------------------------------------------------------------------- #
#  The review verdict                                                          #
# --------------------------------------------------------------------------- #
class _ReviewEngine:
    """An engine whose only behaviour is to submit one review."""

    name = "stub"

    def __init__(self, verdict, defects):
        self.verdict, self.defects = verdict, defects

    def generate(self, *, tool_executor, tools, **kw):
        if any(t["name"] == "submit_review" for t in tools):
            tool_executor("submit_review",
                          {"verdict": self.verdict, "defects": self.defects})
        return _Turn("")


@pytest.mark.parametrize("verdict", ["revise", "fail", "reject", "needs_work"])
def test_any_verdict_that_is_not_pass_sends_the_work_back(verdict):
    """The enum says pass|revise; a model returned "fail".

    Testing `== "revise"` read that as a pass and silently discarded three
    defects the critic had just raised. With a two-value enum these models still
    produce a third value, so the default has to be the one that re-examines the
    work rather than the one that ships it.
    """
    a = _agent(_ReviewEngine(verdict, ["the trajectory never redraws"]),
               ag.LoopPolicy(plan=False, review=True))
    assert a._review() == ["the trajectory never redraws"]


def test_pass_really_does_pass():
    a = _agent(_ReviewEngine("pass", []), ag.LoopPolicy(plan=False, review=True))
    assert a._review() == []


def test_a_verdict_with_no_defects_does_not_trigger_a_repair_round():
    """'revise' with nothing to act on would loop for no reason."""
    a = _agent(_ReviewEngine("revise", []), ag.LoopPolicy(plan=False, review=True))
    assert a._review() == []


def test_the_work_log_states_verification_unmissably():
    """The critic claimed 'no evidence this was verified' while the log said it was."""
    a = _agent(_Engine([("", [])]), ag.LoopPolicy(plan=False, review=False))
    a.tool_events = [{
        "name": "create_simulation", "input": {},
        "result": {"status": "ok", "verification": {"ran": True, "ok": True},
                   "output_files": [{"name": "sim.html"}]},
    }]
    assert "OPENED IN A REAL BROWSER" in a._work_summary()


# --------------------------------------------------------------------------- #
#  The design critic: judging the picture, not the code                        #
# --------------------------------------------------------------------------- #
class _VisionEngine:
    """An engine that records what it was shown and returns a fixed verdict."""

    name = "stub"

    def __init__(self, verdict, problems, vision="gemma4:cloud"):
        self.verdict, self.problems, self._vision = verdict, problems, vision
        self.saw_image = False
        self.model_used = ""

    def vision_model(self):
        return self._vision

    def generate(self, *, messages, tool_executor, model=None, **kw):
        self.model_used = model or ""
        self.saw_image = any(m.get("images") for m in messages)
        tool_executor("submit_visual_review",
                      {"verdict": self.verdict, "problems": self.problems})
        return _Turn("")


def test_the_critic_is_only_paid_for_at_the_deepest_effort():
    """A vision call on every quick answer would make the product slower
    exactly when people want it fast."""
    from app.services.orchestration.design_critic import for_turn

    engine = _VisionEngine("good", [])
    assert for_turn(engine, "weave") is None
    assert for_turn(engine, "spool") is None
    assert for_turn(engine, "tapestry") is not None


def test_no_vision_model_means_no_critic():
    """Asking a text-only model to review a screenshot returns a confident
    description of an image it never saw."""
    from app.services.orchestration.design_critic import for_turn

    assert for_turn(_VisionEngine("good", [], vision=""), "tapestry") is None
    assert for_turn(object(), "tapestry") is None


def test_the_critic_actually_sends_the_image():
    from app.services.orchestration.design_critic import for_turn

    engine = _VisionEngine("needs_work", ["the curve is cut off at the top"])
    critic = for_turn(engine, "tapestry")
    assert critic("BASE64DATA", "Projectile Motion", "create_simulation") == [
        "the curve is cut off at the top"
    ]
    assert engine.saw_image, "the screenshot never reached the model"
    assert engine.model_used == "gemma4:cloud"


def test_good_is_a_cheap_answer():
    from app.services.orchestration.design_critic import for_turn

    engine = _VisionEngine("good", [])
    assert for_turn(engine, "tapestry")("IMG", "t", "create_diagram") == []


def test_needs_work_with_nothing_actionable_is_treated_as_good():
    """'make it better' is not something a model can act on."""
    from app.services.orchestration.design_critic import for_turn

    engine = _VisionEngine("needs_work", ["", "  ", "short"])
    assert for_turn(engine, "tapestry")("IMG", "t", "create_diagram") == []


def test_a_polish_note_withholds_the_artifact_and_asks_for_better():
    """It works, so the language is improvement — but it is still not shown yet.

    Releasing it and asking for a better one afterwards puts two versions in
    the transcript and leaves the reader to work out which is current.
    """
    verdict = Verdict(checked=True, ok=True, attempt=1,
                      polish_notes=["the trajectory is clipped at the top of the chart"])
    assert verdict.needs_polish and not verdict.released
    out = ArtifactGate.apply({"status": "ok", "output_files": [{"s3_key": "k"}]},
                             verdict, "create_simulation")
    assert out["status"] == "needs_polish"
    assert out["verified"] is True, "nothing is broken; it renders"
    assert "output_files" not in out
    assert "clipped at the top" in out["error"]
    assert "Change the SPEC" in out["error"]


def test_polish_is_skipped_on_the_final_attempt():
    """Sending the model back to improve something it can no longer resubmit
    is a round trip for nothing."""
    calls = []
    gate = ArtifactGate("proj", polish=lambda *a: calls.append(a) or ["something"])
    gate._attempts["proj:create_diagram:t"] = MAX_REPAIRS - 1
    # No html in the result, so check() returns before probing — enough to show
    # the budget arithmetic without needing a browser.
    gate.check("create_diagram", {"title": "t"}, {"status": "ok"})
    assert calls == []


# --------------------------------------------------------------------------- #
#  Output budget                                                               #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("effort", ["spool", "weave", "tapestry", None, "nonsense"])
def test_the_output_budget_is_always_positive(effort):
    """-1 means 'no limit' to a local Ollama and is a 400 to a cloud model.

        400 {"error": "max_tokens must be positive, got: -1"}

    Every Tapestry turn on a cloud model therefore failed and fell through to
    the deterministic offline engine: the deepest, slowest setting reliably
    produced the worst answer in the product.
    """
    from app.runtime import num_predict_for

    for ctx in (4096, 8192, 131072, 262144):
        n = num_predict_for(effort, ctx)
        assert n > 0, f"{effort} at ctx={ctx} produced {n}"
        # The floor is deliberately allowed to exceed a very small window — a
        # model that mis-reports a tiny context still gets usable room, and
        # Ollama clamps. Only check the ratio where the window is real.
        if ctx >= 8192:
            assert n <= ctx


def test_the_deepest_level_still_gets_room_for_a_long_file():
    """The budget exists to stop a fixed ceiling truncating generated files."""
    from app.runtime import num_predict_for

    assert num_predict_for("tapestry", 131072) > 60_000
    assert num_predict_for("tapestry", 131072) < 131072


# --------------------------------------------------------------------------- #
#  Conversation shape                                                          #
# --------------------------------------------------------------------------- #
def test_adopting_a_plan_leaves_the_turn_with_the_user():
    """A conversation must never be handed to the model ending on its own turn.

    The plan is appended as an assistant message so it reads back as a
    commitment the model made. Left there, the conversation ENDS on an
    assistant message and a model asked to continue from its own last turn
    returns empty content and no tool calls — so the supervisor correctly sees
    no progress and stops. A turn that planned successfully then produced
    nothing, while a turn whose planning round FAILED went on to do the work.
    Planning made the product worse.
    """
    a = _agent(_Engine([("", [])]), ag.LoopPolicy(plan=False, review=False))
    a._adopt_plan({"surface": "artifact", "goal": "g", "steps": ["one", "two"]})
    assert a.messages[-1]["role"] == "user"
    assert a.messages[-2]["role"] == "assistant"
    assert "plan" in a.messages[-2]["content"].lower()


def test_every_generation_is_asked_a_question():
    """The invariant, checked where it actually matters: at the call site."""
    engine = _Engine([("done", [("create_simulation", {})])])
    a = _agent(engine, ag.LoopPolicy(plan=False, review=False, max_continuations=1))

    seen: list[str] = []
    real = engine.generate

    def spy(*, messages, **kw):
        seen.append(messages[-1]["role"])
        return real(messages=messages, **kw)

    engine.generate = spy
    a._adopt_plan({"surface": "artifact", "goal": "g", "steps": ["one"]})
    a.run()
    assert seen and all(r == "user" for r in seen), seen
