"""Turn-level checkpoint persistence and inspection truthfulness."""
from types import SimpleNamespace


def test_checkpoint_commits_before_turn_finishes_and_continue_recovers(db_session, monkeypatch):
    from app.models import Message, Project, User
    from app.db import SessionLocal
    from app.services.orchestration import agent, orchestrator

    user = User(phone="checkpoint-test", password_hash="x", trust_tier="verified")
    project = Project(user=user, title="Checkpoint", mode="researcher")
    db_session.add(project)
    db_session.commit()
    engine = SimpleNamespace(available=True, translate=lambda text, language: text, name="test")
    monkeypatch.setattr(orchestrator, "get_engine", lambda: engine)
    recovered = []

    def run(self):
        recovered.append(self.plan.exists)
        if not self.plan.exists:
            self.plan = agent.Plan(goal="Deliver both files", surface="workspace",
                                   steps=[agent.PlanStep(1, "Write first"), agent.PlanStep(2, "Write second")])
        self._state_status = "budget"
        self._outstanding = ["Write second"]
        self._save_checkpoint()
        with SessionLocal() as reader:
            saved = reader.query(Message).filter(Message.project_id == project.id,
                                                 Message.role == "assistant").order_by(Message.created_at.desc()).first()
            assert saved.plan["_task_state"]["status"] == "budget"
            assert saved.plan["_task_state"]["project_id"] == project.id
        return agent.AgentResult(text="Incomplete: second file remains", plan=self.plan,
                                 stopped_because="budget", task_state=self.snapshot())

    monkeypatch.setattr(agent.Agent, "run", run)
    orch = orchestrator.Orchestrator()
    first = orch.run_turn(db_session, project, "Build two Python files", "en")
    assert first.plan["_task_state"]["outstanding"] == ["Write second"]
    orch.run_turn(db_session, project, "continue", "en", thread_id=first.thread_id)
    assert recovered == [False, True]


def test_unavailable_browser_cannot_prove_artifact_works(monkeypatch):
    from app.services.tools.base import ToolContext
    from app.services.tools.visuals import _verify_artifact
    from app.services.render import probe

    monkeypatch.setattr(probe, "get_probe", lambda: SimpleNamespace(run=lambda *a, **k:
        SimpleNamespace(available=False, errors=[], warnings=[], screenshot_b64="")))
    ctx = ToolContext(services={"render": SimpleNamespace(enabled=True, verify_html=lambda html:
        {"errors": [], "warnings": []})})
    result = _verify_artifact(ctx, {"html": "<html><body>Hello</body></html>"})
    assert result["status"] == "unverified"
    assert result["executed"] is False
    assert "unavailable" in result["note"]


def test_persisted_artifact_keeps_latest_inspection_and_version():
    from app.services.orchestration.orchestrator import _artifacts_from_events, _step_timeline
    events = [
        {"event": "artifact", "data": {"url": "draft", "visual_id": "v", "verified": False}},
        {"event": "artifact", "data": {"url": "edited", "visual_id": "v", "verified": True}},
    ]
    assert _artifacts_from_events(events) == [{"url": "edited", "visual_id": "v", "verified": True}]
    interrupted = _step_timeline([{"event": "step_start", "data": {"id": "s", "tool": "run_analysis"}}])
    assert interrupted[0]["status"] == "interrupted"


def test_desktop_restart_exposes_and_preserves_interrupted_plan(db_session, monkeypatch):
    from app.models import Message, Project, User
    from app.config import settings
    from app.tasks import recover_desktop_jobs
    from app.api.threads import _has_content

    user = User(phone="restart-checkpoint-test", password_hash="x")
    project = Project(user=user, title="Restart", mode="researcher")
    message = Message(project=project, role="assistant", content_en="", content_sw="",
                      plan={"steps": [{"n": 1, "title": "Finish", "status": "active"}],
                            "_task_state": {"version": 1, "status": "running", "outputs": [{"name": "saved"}]}})
    db_session.add(message)
    db_session.commit()
    monkeypatch.setattr(settings, "environment", "desktop")
    recover_desktop_jobs()
    db_session.refresh(message)
    assert _has_content(message)
    assert message.plan["_task_state"]["status"] == "interrupted"
    assert message.plan["_task_state"]["outputs"] == [{"name": "saved"}]


def test_artifact_identity_does_not_depend_on_shared_filename():
    from app.services.orchestration.orchestrator import _artifact_storage_key
    assert _artifact_storage_key("/api/artifact/render/one_chart.html?exp=123&sig=a") == "render/one_chart.html"
    assert _artifact_storage_key("/api/artifact/render/two_chart.html?exp=123&sig=b") == "render/two_chart.html"
    assert _artifact_storage_key("/other/render/one_chart.html") == ""


def test_resumed_calculation_keeps_bounded_grounding_evidence():
    from app.services.orchestration import agent as ag
    from tests.test_agent_loop import _Engine, _agent
    a = _agent(_Engine([]), ag.LoopPolicy(plan=False, review=False))
    a.tool_events = [{"name": "run_analysis", "input": {"code": "secret source"},
                      "result": {"status": "ok", "stdout": "sum: 17", "run_id": "run1", "dataset_id": "data1"}}]
    state = a.snapshot()
    event = state["tool_events"][0]
    assert "code" not in event["input"]
    assert event["result"]["stdout"] == "sum: 17"
    assert event["result"]["evidence_excerpted"] is True
    assert event["result"]["run_id"] == "run1"
    assert ag.classify_request("What is code?") == "chat"


def test_one_pass_incomplete_handoff_replaces_provisional_stream(db_session, monkeypatch):
    from app.models import Project, User
    from app.services.orchestration import agent, orchestrator
    from app.services.steering import get_steering
    project = Project(user=User(phone="stream-checkpoint", password_hash="x", trust_tier="verified"),
                      title="Stream", mode="researcher")
    db_session.add(project)
    db_session.commit()
    monkeypatch.setattr(orchestrator, "get_engine", lambda: SimpleNamespace(
        available=True, streams=True, translate=lambda t, l: t, name="test"))

    def run(self):
        self.emit("token", {"text": "Everything works."})
        return agent.AgentResult(text="Incomplete: browser validation unavailable", passes=1,
                                 stopped_because="stalled", task_state={"status": "stalled"})
    monkeypatch.setattr(agent.Agent, "run", run)
    emitted = []
    message, _ = orchestrator.Orchestrator()._process(db_session, project, "Build a page", "en", None,
                                                    emit=lambda event, data: emitted.append((event, data)))
    get_steering().finish(message.id)
    restarts = [i for i, event in enumerate(emitted) if event[0] == "answer_restart"]
    assert restarts
    final_tokens = "".join(data["text"] for event, data in emitted[restarts[-1] + 1:] if event == "token")
    assert final_tokens == message.content_en
    assert "Everything works" not in final_tokens


def test_continue_keeps_sql_tools_and_saved_outputs(db_session, monkeypatch):
    from app.models import Message, Project, User
    from app.services.orchestration import agent, orchestrator
    orch = orchestrator.Orchestrator()
    project = Project(user=User(phone="sql-resume-checkpoint", password_hash="x", trust_tier="verified"),
                      title="SQL resume", mode="researcher")
    db_session.add(project)
    db_session.commit()
    thread = orch.memory.get_thread(db_session, project, None)
    saved = Message(project=project, thread_id=thread.id, role="assistant", content_en="Incomplete",
                    plan={"_task_state": {"version": 1, "project_id": project.id, "dataset_id": None,
                          "status": "budget", "plan": {"surface": "analysis", "steps": [{"title": "Calculate"}]},
                          "tool_events": [{"name": "query_warehouse", "input": {}, "result": {
                              "status": "ok", "output_files": [{"name": "saved.csv", "s3_key": "render/saved.csv"}]}}]}})
    db_session.add(saved)
    db_session.commit()
    monkeypatch.setattr(orchestrator, "get_engine", lambda: SimpleNamespace(
        available=True, translate=lambda t, l: t, name="test"))
    monkeypatch.setattr(orchestrator, "get_warehouse", lambda: SimpleNamespace(enabled=True))
    def run(self):
        assert "query_warehouse" in {tool["name"] for tool in self.tools}
        return agent.AgentResult(text="Recovered", plan=self.plan, stopped_because="budget",
                                 task_state=self.snapshot())
    monkeypatch.setattr(agent.Agent, "run", run)
    result = orch.run_turn(db_session, project, "continue", "en", thread_id=thread.id)
    assert any(artifact["name"] == "saved.csv" for artifact in result.artifacts)
