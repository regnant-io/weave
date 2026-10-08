"""Acceptance-driven execution and checkpoint recovery without an LLM/runtime."""
from app.services.orchestration import agent as ag
from tests.test_agent_loop import _Engine, _agent, _Turn


def test_one_output_cannot_close_unexecuted_plan_requirements():
    engine = _Engine([("Everything is complete.", [("create_simulation", {})])])
    a = _agent(engine, ag.LoopPolicy(plan=False, review=False, max_continuations=5),
               tool_executor=lambda *_: {"status": "ok", "verified": True,
                                          "output_files": [{"s3_key": "render/one", "name": "one.html"}]})
    a.plan = ag.Plan(surface="artifact", steps=[ag.PlanStep(1, "build scene"),
                                                 ag.PlanStep(2, "Export a second printable diagram")])
    result = a.run()
    assert result.stopped_because == "stalled"
    assert a.plan.steps[0].status == "done"
    assert a.plan.steps[1].status == "pending"
    assert "second printable diagram" in result.text
    assert "Everything is complete" not in result.text


def test_new_prose_does_not_buy_another_execution_budget():
    engine = _Engine([("I will continue.", []), ("The plan is ready.", [])])
    a = _agent(engine, ag.LoopPolicy(plan=False, review=False, max_continuations=8))
    a.plan = ag.Plan(surface="artifact", steps=[ag.PlanStep(1, "Build custom controls")])
    assert a.run().stopped_because == "stalled"
    assert engine.calls == 2


def test_dependencies_and_acceptance_require_actual_tool_evidence():
    a = _agent(_Engine([("", [])]), ag.LoopPolicy(plan=False, review=False))
    a.plan = ag.Plan(surface="workspace", checks=["Run the project tests"], steps=[
        ag.PlanStep(1, "Add persistence"), ag.PlanStep(2, "Validate persistence", dependencies=[1])])
    a.tool_events = [{"name": "workspace_write", "input": {"path": "state.py"},
                      "result": {"status": "ok", "path": "state.py"}}]
    assert a._apply_plan_update({"step": 2, "status": "done", "evidence": [1]})["status"] == "error"
    assert a._apply_plan_update({"step": 1, "status": "done", "evidence": [1]})["status"] == "ok"
    assert a._apply_plan_update({"step": 2, "status": "done", "evidence": [1], "checks": [1]})["status"] == "error"
    a.tool_events.append({"name": "workspace_check", "input": {}, "result": {"status": "ok", "passed": True}})
    assert a._apply_plan_update({"step": 2, "status": "done", "evidence": [2], "checks": [1]})["status"] == "ok"
    assert a.plan.accepted_checks == [1]


def test_current_artifact_is_inspected_once_and_each_revision_is_rechecked():
    calls = []
    engine = _Engine([
        ("draft", [("create_simulation", {"title": "Motion"})]),
        ("fixed", [("update_visual", {"visual_id": "v1"})]),
    ])

    def execute(name, args):
        calls.append((name, args))
        if name == "verify_artifact":
            return ({"status": "error", "ok": False, "executed": True, "errors": ["canvas is empty"]}
                    if len([c for c in calls if c[0] == name]) == 1 else
                    {"status": "ok", "ok": True, "executed": True})
        return {"status": "ok", "visual_id": "v1", "output_files": [{"name": "motion.html", "s3_key": "k"}]}

    a = _agent(engine, ag.LoopPolicy(plan=False, review=False), tool_executor=execute)
    a.tools.extend([{"name": "update_visual"}, {"name": "verify_artifact"}])
    a.plan = ag.Plan(surface="artifact", steps=[ag.PlanStep(1, "Build scene"), ag.PlanStep(2, "Check scene")])
    result = a.run()
    assert result.stopped_because == "finished"
    assert engine.calls == 2
    assert len([call for call in calls if call[0] == "verify_artifact"]) == 2
    a._inspect_outputs()
    assert len([call for call in calls if call[0] == "verify_artifact"]) == 2


def test_an_unavailable_browser_never_counts_as_verified():
    def execute(name, args):
        if name == "verify_artifact":
            return {"status": "unverified", "ok": False, "executed": False, "error": "Browser is unavailable"}
        return {"status": "ok", "visual_id": "v", "output_files": [{"name": "x.html", "s3_key": "k"}]}

    a = _agent(_Engine([("Verified.", [("create_simulation", {})])]),
               ag.LoopPolicy(plan=False, review=False), tool_executor=execute)
    a.tools.append({"name": "verify_artifact"})
    a.plan = ag.Plan(surface="artifact", steps=[ag.PlanStep(1, "Build scene")])
    result = a.run()
    assert result.stopped_because in {"stalled", "budget"}
    assert "Browser is unavailable" in result.text
    assert a.plan.steps[0].status == "pending"


def test_explicit_continue_restores_work_and_gets_a_fresh_bounded_budget():
    saved = {"version": 1, "status": "budget", "passes": 8, "plan": {
        "surface": "workspace", "goal": "working app", "steps": [
            {"title": "Build project", "status": "done", "evidence": [1]},
            {"title": "Check project", "status": "pending"}]}, "tool_events": [
        {"name": "workspace_write", "input": {"path": "a.py"}, "result": {"status": "ok", "path": "a.py"}}]}
    checkpoints = []
    a = _agent(_Engine([("Checked.", [("workspace_check", {})])]),
               ag.LoopPolicy(plan=True, review=False, max_total_passes=2),
               initial_state=saved, checkpoint=checkpoints.append,
               tool_executor=lambda *_: {"status": "ok", "passed": True})
    a.tools.append({"name": "workspace_check"})
    result = a.run()
    assert result.stopped_because == "finished"
    assert result.passes == 1
    assert result.task_state["total_passes"] == 9
    assert len(result.tool_events) == 2
    assert checkpoints[-1]["status"] == "finished"


def test_replanning_preserves_open_requirements_and_constraints():
    a = _agent(_Engine([("", [])]), ag.LoopPolicy(plan=False, review=False))
    a._adopt_plan({"surface": "artifact", "steps": ["Add keyboard controls"],
                   "checks": ["Arrow keys move the object"], "constraints": ["Must work offline"]})
    a._adopt_plan({"surface": "artifact", "steps": ["Build scene"]})
    assert any(s.title == "Add keyboard controls" for s in a.plan.open_steps())
    assert a.plan.checks == ["Arrow keys move the object"]
    assert a.plan.constraints == ["Must work offline"]


def test_simple_edits_and_chat_remain_lightweight_even_at_deep_effort():
    for prompt in ("Hi", "Change the heading spelling to Colour"):
        p = ag.LoopPolicy.for_request("tapestry", prompt)
        assert not p.plan and not p.review
        assert p.max_total_passes == 2


def test_a_different_output_does_not_repair_a_failed_artifact():
    a = _agent(_Engine([("", [])]), ag.LoopPolicy(plan=False, review=False))
    a.tool_events = [
        {"name": "create_simulation", "input": {"title": "First"}, "result": {"status": "error", "error": "bad spec"}},
        {"name": "create_simulation", "input": {"title": "Second"}, "result": {"status": "ok", "output_files": [{"name": "second.svg"}]}},
    ]
    assert any("bad spec" in gap for gap in a._gaps())


def test_self_audit_failure_preserves_an_explicit_blocker():
    class AuditUnavailable(_Engine):
        def generate(self, *, tools, **kwargs):
            if any(t["name"] == "submit_review" for t in tools):
                raise TimeoutError("review is unavailable")
            return _Turn("Delivered.")

    a = _agent(AuditUnavailable([]), ag.LoopPolicy(plan=False, review=True, review_on_any_work=True))
    a.tool_events = [{"name": "web_search", "input": {}, "result": {"status": "ok"}}]
    result = a.run()
    assert result.stopped_because == "stalled"
    assert "self-audit could not run" in result.text


def test_checkpoint_compaction_preserves_and_renumbers_step_evidence():
    a = _agent(_Engine([("", [])]), ag.LoopPolicy(plan=False, review=False))
    a.plan = ag.Plan(steps=[ag.PlanStep(1, "Inspect existing code", status="done", evidence=[2])])
    a.tool_events = [{"name": "workspace_read", "input": {"path": str(i)},
                      "result": {"status": "ok"}} for i in range(450)]
    saved = a.snapshot()
    assert len(saved["tool_events"]) == 400
    citation = saved["plan"]["steps"][0]["evidence"][0]
    assert saved["tool_events"][citation - 1]["input"]["path"] == "1"


def test_sql_execution_satisfies_analysis_delivery_and_acceptance():
    engine = _Engine([("The mean is 12.", [
        ("query_warehouse", {"sql": "select avg(value) as mean from measurements"}),
        ("update_plan", {"step": 1, "status": "done", "evidence": [1], "checks": [1]}),
    ])])
    a = _agent(engine, ag.LoopPolicy(plan=False, review=False),
               tool_executor=lambda *_: {"status": "ok", "columns": ["mean"], "rows": [[12]], "row_count": 1})
    a.tools.append({"name": "query_warehouse"})
    a.plan = ag.Plan(surface="analysis", steps=[ag.PlanStep(1, "Calculate the mean")], checks=["Compute the mean from actual data"])
    result = a.run()
    assert result.stopped_because == "finished"
    assert a.plan.accepted_checks == [1]
    assert result.task_state["tool_events"][0]["result"]["rows"] == [[12]]


def test_overflow_of_critical_evidence_is_an_explicit_recovery_boundary():
    a = _agent(_Engine([("", [])]), ag.LoopPolicy(plan=False, review=False))
    a.plan = ag.Plan(surface="workspace", steps=[ag.PlanStep(1, "Check project", status="done")])
    a.tool_events = [{"name": "workspace_write", "input": {"path": f"file{i}.py"},
                      "result": {"status": "ok", "path": f"file{i}.py"}} for i in range(450)]
    saved = a.snapshot()
    assert len(saved["tool_events"]) == 400
    assert saved["history_incomplete"] is True
    resumed = _agent(_Engine([("Done.", [])]), ag.LoopPolicy(plan=False, review=False), initial_state=saved)
    assert any("omitted critical evidence" in gap for gap in resumed._gaps())


def test_restoring_a_long_checkpoint_preserves_every_commitment():
    plan = ag.Plan(goal="Complete all requirements", steps=[
        ag.PlanStep(n, f"Requirement {n}", dependencies=[n - 1] if n > 1 else []) for n in range(1, 21)],
        checks=[f"Acceptance {n}" for n in range(20)],
        constraints=[f"Constraint {n}" for n in range(20)], accepted_checks=[1, 20])
    a = _agent(_Engine([("", [])]), ag.LoopPolicy(plan=False, review=False),
               initial_state={"version": 1, "plan": plan.to_json()})
    assert a.plan.to_json() == plan.to_json()
    assert len(a.snapshot()["plan"]["steps"]) == 20


def test_repeated_replans_preserve_constraints_checks_and_dependency_identity():
    a = _agent(_Engine([("", [])]), ag.LoopPolicy(plan=False, review=False))
    a._adopt_plan({"surface": "workspace", "steps": ["Inspect inputs", "Implement feature", "Validate feature"],
                   "dependencies": ["2:1", "3:2"], "checks": ["Initial test"], "constraints": ["Remain offline"]})
    a.plan.get(1).status = "done"
    a.plan.accepted_checks = [1]
    for n in range(20):
        a._adopt_plan({"surface": "workspace", "steps": ["Validate feature", f"Extra requirement {n}"],
                       "checks": [f"Extra check {n}"], "constraints": [f"Extra constraint {n}"]})
    assert len(a.plan.steps) == 23
    assert len(a.plan.checks) == 21
    assert len(a.plan.constraints) == 21
    inspect = next(step for step in a.plan.steps if step.title == "Inspect inputs")
    implement = next(step for step in a.plan.steps if step.title == "Implement feature")
    validate = next(step for step in a.plan.steps if step.title == "Validate feature")
    assert inspect.status == "done"
    assert implement.dependencies == [inspect.n]
    assert validate.dependencies == [implement.n]
    assert a.plan.accepted_checks == [1]
    restored = ag.Plan.from_json(a.snapshot()["plan"])
    assert restored.to_json() == a.plan.to_json()
    assert a._apply_plan_update({"step": validate.n, "status": "active"})["status"] == "error"
