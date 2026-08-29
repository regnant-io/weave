"""The supervised agent loop: plan, work, check, repair — then answer.

WHY THE OLD SHAPE COULD NOT PRODUCE GOOD WORK
---------------------------------------------
The previous turn was one call to `engine.generate()`. That call runs a tool
loop and returns as soon as the model emits a message with no tool calls in it.
So the model decided, alone and unaccountably, when the work was finished. In
practice that produces the shape everyone recognises:

    prompt -> a paragraph -> one artifact -> "Let me know if you'd like me to
    add X!" -> stop

Nothing was wrong with any individual component. The model was not lazy; it had
simply satisfied the only condition the system imposed on it, which was to stop
emitting tool calls. A system whose sole definition of "done" is "the model went
quiet" gets exactly this.

WHAT REPLACES IT
----------------
A supervisor with its own opinion about whether the work is finished:

  1. PLAN     — for anything non-trivial, one cheap call that writes down the
                goal, the steps, and how the result will be CHECKED. The plan is
                capability-aware: without it, every model plans to load Three.js
                from a CDN and inline textures from URLs, which the artifact
                sandbox forbids, so the work is wrong before a line is written.
  2. WORK     — the tool loop, but bounded by the plan rather than by the
                model's inclination to stop.
  3. GAP CHECK— when the model goes quiet, the supervisor asks whether the plan
                is actually complete and whether everything it built was
                verified. If not, it says so and the model continues. This is
                the mechanism that ends "emit and run".
  4. REVIEW   — a critic pass against the original request. Not the same model
                turn congratulating itself: a separate call, given the work and
                asked what is wrong with it, with a schema that makes "nothing"
                an explicit verdict rather than the path of least resistance.
  5. REPAIR   — the defects go back as work. Bounded.

Everything here is bounded twice: by a pass budget, and by a NO-PROGRESS rule. A
pass that produces no tool calls, no plan movement and no new text is a loop
that has stopped advancing, and the right response is to stop rather than to
spend another minute proving it again.

DESIGNED FOR THE MODELS THAT ACTUALLY RUN HERE
----------------------------------------------
Every structured exchange uses a FLAT schema — `steps` is a list of strings, not
a list of objects. This is not a simplification for its own sake: given a nested
schema, gpt-oss:20b returns objects missing the required keys and gpt-oss:120b
returns bare strings where objects were specified. A list of strings is the
richest shape all of these models emit reliably, and a plan of seven clear
sentences is worth more than a malformed plan of seven objects.

Effort governs how much of this machinery runs — see `LoopPolicy`. A one-line
question does not get a planning round.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger("weave.agent")

#: Loop-control tools. These are NOT capabilities — they do not touch the world,
#: they only move the supervisor's state — so they live here rather than in the
#: registry, and are appended to whatever real tools the turn was given.
PLAN_TOOL = {
    "name": "submit_plan",
    "description": (
        "Write down how you will do this task, BEFORE you start. Call this exactly "
        "once. Keep it short and concrete — steps someone could check off, not "
        "phases of a project. If the task is genuinely one action, say so in one step."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "surface": {
                "type": "string",
                "enum": ["artifact", "workspace", "analysis", "answer"],
                "description": (
                    "WHERE this is delivered. 'artifact' = something the user looks "
                    "at or interacts with inside the conversation (a 3D scene, a "
                    "simulation, a diagram, a chart, a page, a deck) — made with ONE "
                    "create_* call. 'workspace' = a real codebase the user will "
                    "download and run. 'analysis' = work on their dataset. 'answer' = "
                    "prose, research, explanation. Choose one; it decides which tools "
                    "you get."
                ),
            },
            "goal": {
                "type": "string",
                "description": "One sentence: what DONE looks like, in observable terms.",
            },
            "steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "3-6 short imperative steps, one concrete action each. Fewer, "
                    "bigger steps beat many small ones — every step is something "
                    "you have to come back and close."
                ),
            },
            "checks": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "How you will VERIFY the result really works — the command you "
                    "will run, the page you will open, the number you will sanity-check."
                ),
            },
        },
        "required": ["surface", "goal", "steps"],
    },
}

UPDATE_TOOL = {
    "name": "update_plan",
    "description": (
        "Mark a plan step finished, failed or no-longer-needed as you go. Call it "
        "the moment a step is genuinely done — the step list is what the user "
        "watches to know where you are, and it is also how this system knows the "
        "work is complete. A step is not 'done' because you wrote the code; it is "
        "done when the code ran, or the page opened."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "step": {"type": "integer", "description": "Step number, starting at 1."},
            "status": {"type": "string", "enum": ["done", "failed", "skipped", "active"]},
            "note": {"type": "string", "description": "One line: the outcome, or why not."},
        },
        "required": ["step", "status"],
    },
}

REVIEW_TOOL = {
    "name": "submit_review",
    "description": "Record your judgement of the work. Call this exactly once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["pass", "revise"],
                "description": "'pass' only if you would be happy to sign this off.",
            },
            "defects": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Specific, actionable problems. Each one names what is wrong and "
                    "what would fix it. Empty when the verdict is 'pass'."
                ),
            },
        },
        "required": ["verdict"],
    },
}


# --------------------------------------------------------------------------- #
#  The plan                                                                    #
# --------------------------------------------------------------------------- #
@dataclass
class PlanStep:
    n: int
    title: str
    status: str = "pending"      # pending | active | done | failed | skipped
    note: str = ""

    def to_json(self) -> dict:
        return {"n": self.n, "title": self.title, "status": self.status, "note": self.note}


@dataclass
class Plan:
    goal: str = ""
    steps: list[PlanStep] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    #: artifact | workspace | analysis | answer. Decides the toolset for the
    #: working phase — see `Agent._tools_with_loop_control`.
    surface: str = ""

    @property
    def exists(self) -> bool:
        return bool(self.steps)

    def open_steps(self) -> list[PlanStep]:
        """Steps that still owe the user something."""
        return [s for s in self.steps if s.status in {"pending", "active"}]

    def failed_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status == "failed"]

    def get(self, n: int) -> PlanStep | None:
        for s in self.steps:
            if s.n == n:
                return s
        return None

    def render(self) -> str:
        """The plan as the model should see it, with live status."""
        mark = {"done": "[x]", "failed": "[!]", "skipped": "[-]",
                "active": "[>]", "pending": "[ ]"}
        head = "YOUR PLAN"
        if self.surface:
            head += f" [delivering as: {self.surface}]"
        if self.goal:
            head += "\n  goal: " + self.goal
        lines = [head]
        for s in self.steps:
            suffix = f"  — {s.note}" if s.note else ""
            lines.append(f"  {mark.get(s.status, '[ ]')} {s.n}. {s.title}{suffix}")
        if self.checks:
            lines.append("How you said you would check it:")
            lines += [f"  - {c}" for c in self.checks]
        return "\n".join(lines)

    def to_json(self) -> dict:
        return {
            "goal": self.goal,
            "surface": self.surface,
            "steps": [s.to_json() for s in self.steps],
            "checks": list(self.checks),
        }


# --------------------------------------------------------------------------- #
#  Policy                                                                      #
# --------------------------------------------------------------------------- #
@dataclass
class LoopPolicy:
    """How much supervision this turn gets.

    Every one of these costs a model call, and a model call on a hosted frontier
    model costs real time. A greeting must not pay for a planning round; a
    request to build a working application must not be allowed to skip one.
    """

    plan: bool = True
    review: bool = True
    max_continuations: int = 3       # gap-driven "keep going" passes
    max_review_rounds: int = 1       # critic -> repair cycles
    #: Hard ceiling on GENERATION passes for the whole turn, across every phase.
    #:
    #: The two limits above are per-phase, and they compose multiplicatively:
    #: the working loop may run `max_continuations + 1` passes, and then EACH
    #: review round calls the same loop again with a repair brief. At Tapestry
    #: that is 6 + 2x6 = eighteen generations, each of which may make up to
    #: forty tool calls. Nobody chose eighteen; it is what two independently
    #: reasonable numbers multiply out to, and the first time anyone notices is
    #: when a single question has been running for twenty minutes and the
    #: session quota is gone. A ceiling on the total is the only bound that
    #: cannot be defeated by a new phase being added later.
    max_total_passes: int = 8

    @classmethod
    def for_effort(cls, effort: str | None, *, complex_request: bool) -> "LoopPolicy":
        level = (effort or "weave").lower()
        if level == "spool":
            # Quick answers stay quick. One pass, no ceremony.
            return cls(plan=False, review=False, max_continuations=1,
                       max_review_rounds=0, max_total_passes=2)
        if level == "tapestry":
            return cls(plan=True, review=True, max_continuations=5,
                       max_review_rounds=2, max_total_passes=10)
        # weave (default): supervise real work, stay out of the way of chat.
        return cls(
            plan=complex_request,
            review=complex_request,
            max_continuations=3 if complex_request else 1,
            max_review_rounds=1 if complex_request else 0,
            max_total_passes=6 if complex_request else 2,
        )


#: Signals that a request is real work rather than conversation. Deliberately
#: generous — the cost of planning a turn that did not need it is a few seconds;
#: the cost of NOT planning a build is the failure mode this module exists for.
_BUILD_WORDS = (
    "build", "make", "create", "write", "implement", "code", "app", "game", "site",
    "website", "simulate", "simulation", "design", "generate", "draw", "chart",
    "graph", "diagram", "analyse", "analyze", "clean", "fix", "debug", "refactor",
    "deck", "presentation", "slides", "report", "dashboard", "3d", "scene",
    "tengeneza", "unda", "andika", "changanua", "chora", "tumia", "boresha",
)


def looks_like_work(text: str) -> bool:
    """Whether this request should be planned before it is attempted."""
    t = (text or "").lower()
    if len(t) > 220:
        return True
    if any(w in t for w in _BUILD_WORDS):
        return True
    # Several sentences usually means several requirements.
    return t.count("?") + t.count(".") >= 3


# --------------------------------------------------------------------------- #
#  Result                                                                      #
# --------------------------------------------------------------------------- #
@dataclass
class AgentResult:
    text: str = ""
    tool_events: list[dict] = field(default_factory=list)
    tier_used: str = "fast"
    plan: Plan | None = None
    passes: int = 0
    review_rounds: int = 0
    stopped_because: str = ""


# --------------------------------------------------------------------------- #
#  The loop                                                                    #
# --------------------------------------------------------------------------- #
class Agent:
    """Runs one turn under supervision.

    The orchestrator owns everything about the world — the database, the tool
    registry, the gate, steering. This class owns only the question of whether
    the work is finished, which is the one thing the old design left to the
    model.
    """

    def __init__(
        self,
        *,
        engine,
        system: str,
        messages: list[dict],
        tools: list[dict],
        tool_executor: Callable[[str, dict], dict],
        emit: Callable[[str, dict], None],
        policy: LoopPolicy,
        tier: str = "fast",
        effort: str | None = None,
        model: str | None = None,
        cancel=None,
        user_text: str = "",
        capabilities: set[str] | None = None,
        parallel_safe: set[str] | None = None,
        on_pass_end: Callable[[Any], str | None] | None = None,
    ) -> None:
        self.engine = engine
        self.system = system
        self.messages = list(messages)
        self.tools = list(tools)
        self._tool_executor = tool_executor
        self.emit = emit
        self.policy = policy
        self.tier = tier
        self.effort = effort
        self.model = model
        self.cancel = cancel
        self.user_text = user_text
        self.capabilities = capabilities or set()
        #: Names of tools the registry says may run concurrently with each
        #: other. Passed straight through to the engine, which is where a
        #: model turn's tool calls are actually dispatched.
        self.parallel_safe = parallel_safe or set()
        #: Called after each generation pass. Returns "restart" when the turn was
        #: steered and the conversation was rewritten underneath us, in which
        #: case gap-checking this pass would be judging superseded work.
        self.on_pass_end = on_pass_end

        self.plan = Plan()
        self.tool_events: list[dict] = []
        self._texts: list[str] = []
        self._passes = 0
        self._progress_marker = 0    # bumped by anything that counts as advancing
        self._plan_nags = 0          # how many times we have pressed on open steps

    # -- public ------------------------------------------------------------

    def run(self) -> AgentResult:
        stopped = "finished"

        if self.policy.plan and not self._cancelled():
            self._make_plan()

        if not self._cancelled():
            stopped = self._work()

        if self.policy.review and not self._cancelled() and stopped == "finished":
            stopped = self._review_and_repair() or stopped

        return AgentResult(
            text=_compose(self._texts),
            tool_events=self.tool_events,
            tier_used=self.tier,
            plan=self.plan if self.plan.exists else None,
            passes=self._passes,
            review_rounds=self._review_rounds,
            stopped_because=stopped,
        )

    # -- phase 1: plan -----------------------------------------------------

    _review_rounds = 0

    def _make_plan(self) -> None:
        """One cheap call that writes down the goal, the steps and the checks."""
        self.emit("phase", {"name": "planning"})
        brief = (
            "Before doing anything, plan this task.\n\n"
            f"THE REQUEST:\n{self.user_text[:2000]}\n\n"
            + self._capability_brief()
            + "\nCall `submit_plan` now. Do not do any of the work yet, and do not "
            "call any other tool."
        )
        convo = [*self.messages, {"role": "user", "content": brief}]

        captured: dict = {}

        def executor(name: str, args: dict) -> dict:
            if name == "submit_plan":
                captured.update(args or {})
                return {"status": "ok", "note": "Plan recorded. Now carry it out."}
            # Refuse everything else rather than executing it.
            #
            # Letting the model start working during the planning round sounded
            # harmless and was not: it edited files that did not exist yet,
            # collected two tool errors and spent 37 seconds before writing a
            # plan. Acting before deciding what to do is precisely what the
            # planning round exists to prevent.
            return {
                "status": "rejected",
                "error": "You are planning. Call `submit_plan` first; you can use "
                         f"`{name}` as soon as the plan is recorded.",
            }

        try:
            self.engine.generate(
                system=self.system + "\n\n" + _PLANNER_LAYER,
                messages=convo,
                tools=[PLAN_TOOL],
                tool_executor=executor,
                tier="fast",
                # Planning output is internal scaffolding, not the answer. Letting
                # it stream would put a plan the user never asked to read at the
                # top of every reply.
                on_event=self._silent_events,
                effort="spool",
                model=self.model,
                cancel=self.cancel,
                max_iters=3,
            )
        except Exception as exc:  # noqa: BLE001 - planning is an aid, never a gate
            from .llm import QuotaExhausted
            if isinstance(exc, QuotaExhausted):
                # Out of quota is not a planning problem: the work pass will hit
                # the same wall. Fail now so the user gets the real explanation
                # instead of watching an unplanned turn grind to the same halt.
                raise
            log.warning("planning pass failed (%s); continuing unplanned", exc)
            return

        self._adopt_plan(captured)

    def _adopt_plan(self, raw: dict) -> None:
        steps = _string_list(raw.get("steps"))
        if not steps:
            return
        surface = str(raw.get("surface") or "").strip().lower()
        if surface not in {"artifact", "workspace", "analysis", "answer"}:
            surface = ""
        self.plan = Plan(
            surface=surface,
            goal=str(raw.get("goal") or "").strip()[:400],
            steps=[PlanStep(n=i, title=s[:240]) for i, s in enumerate(steps[:6], start=1)],
            checks=[c[:240] for c in _string_list(raw.get("checks"))[:6]],
        )
        self.emit("plan", self.plan.to_json())
        # The plan enters the conversation as the model's own statement, so it
        # reads back as a commitment it made rather than an instruction it was
        # given. Models follow their own plans considerably better.
        self.messages.append({
            "role": "assistant",
            "content": "Here is my plan:\n" + self.plan.render(),
        })
        # ...and then hand the turn back.
        #
        # Without this the conversation ENDS on an assistant message, and a
        # model asked to continue from its own last turn has nothing to respond
        # to: it returns empty content and no tool calls. The supervisor then
        # correctly observes that no progress was made and stops, so a turn that
        # planned successfully produced nothing at all — while a turn whose
        # planning round FAILED went on to do the work. Planning made the
        # product worse, which is the kind of inversion that is invisible until
        # you watch a whole run.
        self.messages.append({
            "role": "user",
            "content": "Good. Now carry it out, starting with step 1.",
        })

    # -- phase 2: work -----------------------------------------------------

    def _work(self, brief: str | None = None) -> str:
        """Generate, then check whether it is actually finished. Repeat."""
        if brief:
            self.messages.append({"role": "user", "content": brief})

        for _ in range(max(1, self.policy.max_continuations + 1)):
            if self._cancelled():
                return "cancelled"
            if self._passes >= self.policy.max_total_passes:
                log.info("agent hit the whole-turn pass budget (%d)",
                         self.policy.max_total_passes)
                return "budget"

            self._passes += 1
            before = self._progress_marker
            self.emit("phase", {"name": "working", "pass": self._passes})

            result = self.engine.generate(
                system=self._system_with_plan(),
                messages=self.messages,
                tools=self._tools_with_loop_control(),
                tool_executor=self._execute,
                tier=self.tier,
                on_event=self.emit,
                effort=self.effort,
                model=self.model,
                cancel=self.cancel,
                parallel_safe=self.parallel_safe,
            )
            text = (result.text or "").strip()
            if text:
                self._texts.append(text)
                self._progress_marker += 1
            self.messages.append({"role": "assistant", "content": text or "(worked)"})
            self.tier = result.tier_used or self.tier

            if self.on_pass_end is not None:
                signal = self.on_pass_end(result)
                if signal == "restart":
                    # Steered mid-flight. The conversation has been rewritten and
                    # everything above is superseded; start the pass count again
                    # rather than judging work the user has overridden.
                    self._texts.clear()
                    continue
                if signal == "stop":
                    return "cancelled"

            gaps = self._gaps()
            if not gaps:
                return "finished"

            if self._progress_marker == before:
                # Nothing moved this pass: no tool ran, no step changed, no text
                # was written. Another pass would produce the same nothing more
                # slowly, so stop and let the answer stand with its gaps visible.
                log.info("agent made no progress; stopping with %d gaps", len(gaps))
                return "stalled"

            self.emit("continuing", {
                "pass": self._passes,
                "gaps": gaps[:6],
                "remaining": len(self.plan.open_steps()),
            })
            self.messages.append({"role": "user", "content": _continuation_brief(gaps)})

        return "budget"

    def _gaps(self) -> list[str]:
        """What is still outstanding. Empty means genuinely finished.

        This is the supervisor's whole opinion, and it is deliberately narrow:
        only things that are OBSERVABLY incomplete count. Inventing softer
        criteria ("could be more thorough") would produce a loop that never
        terminates and an assistant that never shuts up.
        """
        gaps: list[str] = []

        # Plan steps are a SOFT gap, and deliberately so.
        #
        # The ledger only advances when the model calls `update_plan`, and a
        # model that is doing the work perfectly well but not ticking boxes
        # looks identical to one that has abandoned the task. Nagging it
        # indefinitely produced four passes in which the same four steps were
        # reported outstanding while real work was being done and re-done.
        #
        # So: press twice, then stop pressing. After that only HARD gaps —
        # things observably broken — can keep the loop alive.
        if self._plan_nags < 2:
            open_steps = self.plan.open_steps()
            if open_steps:
                self._plan_nags += 1
                for step in open_steps:
                    gaps.append(f"plan step {step.n} is not finished: {step.title}")

        for step in self.plan.failed_steps():
            gaps.append(
                f"plan step {step.n} failed ({step.note or 'no reason recorded'}) — "
                "either fix it or tell the user plainly that it could not be done"
            )

        # An artifact that was sent back for repair and never resubmitted is the
        # exact failure the gate exists to catch. If the model absorbed the
        # rejection and moved on to its summary, the gate did its job and the
        # supervisor has to insist.
        for event in self.tool_events:
            if (event.get("result") or {}).get("status") != "needs_repair":
                continue
            if self._was_retried_after(event):
                continue
            errors = ((event.get("result") or {}).get("verification") or {}).get("errors") or []
            gaps.append(
                f"`{event.get('name')}` produced something broken and it was never "
                f"fixed: {errors[0] if errors else 'it failed verification'}"
            )

        return gaps

    def _was_retried_after(self, failed: dict) -> bool:
        """Whether the same tool ran again, successfully, after this failure."""
        seen = False
        for event in self.tool_events:
            if event is failed:
                seen = True
                continue
            if not seen or event.get("name") != failed.get("name"):
                continue
            if (event.get("result") or {}).get("status") in {"ok", "success"}:
                return True
        return False

    # -- phase 3: review ---------------------------------------------------

    def _review_and_repair(self) -> str:
        """Ask a critic what is wrong, then fix it."""
        for _ in range(max(0, self.policy.max_review_rounds)):
            if self._cancelled():
                return "cancelled"
            defects = self._review()
            if not defects:
                return "finished"
            self._review_rounds += 1
            self.emit("phase", {"name": "repairing", "defects": len(defects)})
            outcome = self._work(_repair_brief(defects))
            if outcome != "finished":
                return outcome
        return "finished"

    def _review(self) -> list[str]:
        """A separate call whose only job is to find what is wrong.

        Run as its own exchange rather than as a question appended to the working
        conversation. A model asked "are you happy with that?" at the end of its
        own turn says yes — it has just spent the whole turn establishing that
        the work is good. Given the work cold, with a schema in which "revise" is
        as easy to say as "pass", it finds real defects.
        """
        self.emit("phase", {"name": "reviewing"})
        summary = self._work_summary()
        convo = [{
            "role": "user",
            "content": (
                f"THE REQUEST WAS:\n{self.user_text[:1500]}\n\n"
                f"THIS IS WHAT WAS PRODUCED:\n{summary}\n\n"
                "Judge it. Call `submit_review` once."
            ),
        }]

        found: dict = {}

        def executor(name: str, args: dict) -> dict:
            if name == "submit_review":
                found.update(args or {})
                return {"status": "ok"}
            return {"status": "rejected", "error": "only submit_review may be called here"}

        try:
            self.engine.generate(
                system=_CRITIC_LAYER,
                messages=convo,
                tools=[REVIEW_TOOL],
                tool_executor=executor,
                tier="fast",
                on_event=self._silent_events,
                effort="spool",
                model=self.model,
                cancel=self.cancel,
                max_iters=2,
            )
        except Exception as exc:  # noqa: BLE001 - a failed critic never blocks delivery
            from .llm import QuotaExhausted
            if isinstance(exc, QuotaExhausted):
                # The work is already done and delivered by this point; losing
                # the review is a real but acceptable degradation, so this one
                # is swallowed rather than raised.
                log.warning("review skipped: %s", exc)
                return []
            log.warning("review pass failed (%s); accepting the work as-is", exc)
            return []

        verdict = str(found.get("verdict") or "pass").lower()
        defects = [d for d in _string_list(found.get("defects")) if len(d) > 8][:6]
        self.emit("review", {"verdict": verdict, "defects": defects})
        # Anything that is not an explicit "pass" counts as needing work.
        #
        # The enum says pass|revise and the model returned "fail" — which the
        # old `== "revise"` test read as a pass, silently discarding three
        # defects it had just raised. Given a two-value enum these models will
        # still produce a third value; the safe default is the one that makes us
        # look at the work again, not the one that ships it.
        needs_work = verdict != "pass"
        return defects if (needs_work and defects) else []

    def _work_summary(self) -> str:
        """What the critic gets to look at.

        Tool results, not just the prose: a critic shown only the closing
        paragraph reviews the paragraph. What matters is whether the code ran,
        whether the page opened, and whether the artifacts were verified.
        """
        lines: list[str] = []
        if self.plan.exists:
            lines.append(self.plan.render())
            lines.append("")

        for event in self.tool_events[-24:]:
            result = event.get("result") or {}
            status = result.get("status", "ok")
            bits = [f"- {event.get('name')} -> {status}"]
            verification = result.get("verification")
            if isinstance(verification, dict):
                bits.append(
                    "OPENED IN A REAL BROWSER AND RENDERED CLEANLY"
                    if verification.get("ok") else
                    "VERIFICATION FAILED: "
                    + "; ".join(verification.get("errors") or [])[:300]
                )
            if result.get("error"):
                bits.append(f"error: {str(result['error'])[:240]}")
            if result.get("stderr"):
                bits.append(f"stderr: {str(result['stderr'])[:240]}")
            if result.get("exit_code"):
                bits.append(f"exit={result['exit_code']}")
            files = [f.get("name") for f in (result.get("output_files") or [])]
            if files:
                bits.append("produced: " + ", ".join(str(f) for f in files[:5]))
            lines.append(" | ".join(bits))

        if not lines:
            lines.append("(no tools were used)")

        answer = "\n\n".join(self._texts)[-3000:]
        return "WORK LOG:\n" + "\n".join(lines) + "\n\nTHE ANSWER GIVEN:\n" + answer

    # -- tool plumbing -----------------------------------------------------

    def _tools_with_loop_control(self) -> list[dict]:
        """The tools this phase of this turn may use.

        THE SURFACE IS ENFORCED HERE, NOT ASKED FOR IN A PROMPT.

        Told in the system prompt that it can build software AND that it can
        render interactive artifacts, a model handed "build me an interactive 3D
        solar system I can fly through" reliably picks the wrong one: it writes
        an index.html into the workspace, downloads a copy of Babylon by hand,
        and tries to start an HTTP server nobody can reach — when a single
        `create_3d_experience` call produces a verified scene inline. Adding
        firmer wording to the prompt did not fix it, twice.

        So the plan commits to a surface and the surface removes the tools that
        do not belong to it. A model cannot pick the wrong instrument if the
        wrong instrument is not on the tray.

        The escape hatch is deliberate and cheap: `submit_plan` stays available
        in every phase, so a model that genuinely needs the other surface can
        re-plan and get it. What it cannot do is drift there by accident.
        """
        tools = self.tools
        surface = self.plan.surface if self.plan.exists else ""

        if surface == "artifact":
            tools = [t for t in tools if not _is_workspace_authoring(t.get("name", ""))]
        elif surface in {"workspace", "analysis"}:
            # The reverse mistake is real but much cheaper: a codebase does not
            # need the deck renderer. Only the heavyweight visual surfaces go,
            # and verification stays because generated pages still get checked.
            tools = [t for t in tools
                     if t.get("name") not in {"generate_deck", "create_3d_experience",
                                              "generate_3d", "create_animation"}]

        if not self.plan.exists:
            return tools
        # `submit_plan` remains callable so a wrong surface is recoverable.
        return [*tools, UPDATE_TOOL, PLAN_TOOL]

    def _execute(self, name: str, args: dict) -> dict:
        """Intercept loop-control calls; pass everything else through."""
        if name == "update_plan":
            return self._apply_plan_update(args or {})
        if name == "submit_plan":
            # A model re-planning mid-work is usually a sign the original plan
            # was wrong. Accepting it is better than rejecting it and having the
            # model work against a plan it no longer believes in.
            self._adopt_plan(args or {})
            return {"status": "ok", "note": "Plan replaced."}
        result = self._tool_executor(name, args)
        self.tool_events.append({"name": name, "input": args, "result": result})
        self._progress_marker += 1
        return result

    def _apply_plan_update(self, args: dict) -> dict:
        try:
            n = int(args.get("step"))
        except (TypeError, ValueError):
            return {"status": "error", "error": "`step` must be the step number, e.g. 2"}
        step = self.plan.get(n)
        if step is None:
            return {"status": "error",
                    "error": f"there is no step {n}; the plan has "
                             f"{len(self.plan.steps)} steps"}
        status = str(args.get("status") or "done").lower()
        if status not in {"done", "failed", "skipped", "active"}:
            status = "done"
        step.status = status
        step.note = str(args.get("note") or "")[:240]
        self._progress_marker += 1
        self.emit("plan_step", step.to_json())
        remaining = len(self.plan.open_steps())
        return {
            "status": "ok",
            "remaining_steps": remaining,
            "note": ("All steps are marked complete. Before you finish: everything you "
                     "built must have been run or opened, not just written."
                     if remaining == 0 else
                     f"{remaining} step(s) still open."),
        }

    # -- helpers -----------------------------------------------------------

    def _system_with_plan(self) -> str:
        if not self.plan.exists:
            return self.system
        directive = _SURFACE_DIRECTIVE.get(self.plan.surface, "")
        return (
            self.system
            + (("\n\n" + directive) if directive else "")
            + "\n\n"
            + self.plan.render()
            + "\n\nWork through these steps. Call `update_plan` as each one is "
              "genuinely finished — a step is done when the thing RAN, not when it "
              "was written. Do not stop while steps are open."
        )

    def _capability_brief(self) -> str:
        """What this environment can actually do — stated before planning.

        Without this every model plans against the open web it was trained on:
        Three.js from a CDN, textures from URLs, `npm start` on a machine it
        imagines. Those plans are wrong before any code is written, and the
        resulting artifact fails verification for reasons that were decided at
        planning time.
        """
        lines = ["WHAT YOU ARE PLANNING FOR — this environment, not a generic one:"]

        # DECIDE THE SURFACE FIRST. Without this the model treats every request
        # as a web project: it writes an index.html with a `<script src=cdn>`
        # tag into the workspace and tries to start an HTTP server, when a
        # single `create_3d_experience` call would have produced a verified,
        # interactive scene inline in the conversation. The tools were all
        # available; nothing told it which surface the work belonged on.
        if {"render", "workspace"} & self.capabilities:
            lines.append(
                "- FIRST DECIDE WHERE THIS IS DELIVERED. Two different surfaces:\n"
                "    * AN ARTIFACT — something the user looks at and interacts with "
                "inside this conversation: a 3D scene, a simulation, a diagram, a "
                "chart, a knowledge graph, a page, a deck. Produced by ONE tool call, "
                "rendered inline, verified automatically. This is the right choice for "
                "almost anything the user wants to SEE or PLAY WITH. Do not build it "
                "as files in the workspace and do not write an index.html for it.\n"
                "    * WORKSPACE SOFTWARE — a real project the user will download and "
                "run: multiple source files, dependencies, tests, a package. Only when "
                "the deliverable is genuinely a codebase.\n"
                "  'Build me an interactive X I can explore' is an ARTIFACT."
            )
        if "render" in self.capabilities:
            lines.append(
                "- Artifact tools: create_simulation (parameters the user drags), "
                "create_3d_experience (Babylon scene to move through or play with), "
                "create_knowledge_graph (entities and relationships), create_diagram "
                "(flow/tree/timeline), create_animation (a process, drawn in order), "
                "generate_visual (a statistical chart), create_html_page (a document "
                "or small tool), generate_deck (slides)."
            )
            lines.append(
                "- Every artifact is ONE self-contained file that runs with NO "
                "NETWORK: no CDN script, no web font, no remote image, no fetch. "
                "THREE, BABYLON, React and ReactFlow are ALREADY INLINED as globals — "
                "never plan to load them from a CDN, and never plan to use a texture "
                "or model from a URL. Build geometry and colour in code, or download "
                "the asset into the workspace first and pass it in `assets`."
            )
            lines.append(
                "- Everything you render is opened in a real browser before the user "
                "sees it, and comes back to you with any errors. Plan on that check."
            )
        if "workspace" in self.capabilities:
            lines.append(
                "- The workspace is a persistent project directory with a real "
                "container: Node 20, Python 3, git, network access for installing "
                "dependencies. Code written there can and must be RUN. Note that each "
                "command runs to completion — a long-running server started with "
                "`workspace_exec` will simply hit the timeout, so test with a script "
                "that exits, not by starting a server."
            )
        if "analysis" in self.capabilities:
            lines.append(
                "- Data analysis runs in a separate sandbox with pandas/numpy/scipy/"
                "matplotlib, no network, reading only via weave_io.load_dataset()."
            )
        if "websearch" in self.capabilities:
            lines.append("- Live web search and page fetching are available.")
        lines.append(
            "- A step is only finished when it has been executed or opened. Include "
            "the checks in your plan."
        )
        return "\n".join(lines) + "\n"

    def _silent_events(self, kind: str, data: dict) -> None:
        """Event sink for internal passes.

        Planning and review are the supervisor thinking, not the assistant
        answering. Their tokens must not appear in the transcript — but their
        step activity should, so the user can see that a check happened rather
        than watching an unexplained pause.
        """
        if kind in {"token", "thinking", "answer_start"}:
            return
        self.emit(kind, data)

    def _cancelled(self) -> bool:
        return self.cancel is not None and getattr(self.cancel, "is_set", lambda: False)()


# --------------------------------------------------------------------------- #
#  Prompt layers                                                               #
# --------------------------------------------------------------------------- #
_PLANNER_LAYER = """\
YOU ARE PLANNING, NOT ANSWERING.
Produce a short, concrete plan and nothing else. Rules:
- Steps are actions, not phases. "Write the orbital-mechanics function" is a
  step; "Development" is not.
- Include the steps where you RUN or OPEN what you built. Work that has not been
  executed is not finished, and a plan that ends at "write the code" is a plan to
  ship something untested.
- Plan for THIS environment, using the tools described. A step that depends on
  something this environment does not have is a step that will fail.
- 3-6 steps. If it genuinely takes one step, write one.
Call `submit_plan`. Do not begin the work."""

_CRITIC_LAYER = """\
You are reviewing work before it is handed to the person who asked for it. You
did not do this work and you have no stake in it being good.

Judge it against ONE question: if this were handed over now, would the person
who asked get what they asked for?

WHAT YOU CAN AND CANNOT SEE. You are reading a WORK LOG and the answer text.
Artifacts are rendered directly into the conversation, so the user sees them
even though you do not. The log tells you what was produced and whether it was
opened in a real browser. Judge from the log — never from the fact that the
answer text does not contain the code, a link or a preview, because none of
those belong in it.

Look for, in this order:
1. Things claimed but not done. Code described but never run. A file said to be
   complete that was never opened. An artifact reported as working whose
   verification actually FAILED in the log. This is the most common and the most
   damaging defect — treat any gap between what the log shows and what the
   answer claims as a defect.
2. Parts of the request that were quietly dropped or narrowed.
3. Output the log shows to be broken, truncated, or not runnable.
4. Claims stated as fact without support.

Do NOT raise: style preferences, things that could hypothetically be extended,
"consider adding" suggestions, or the absence of code/links/screenshots from the
answer. And never raise "there is no evidence this was verified" when the log
says it was verified — the log is the evidence. A defect is something WRONG, not
something absent from your imagination.

If the work genuinely answers the request, say `pass`. Saying `pass` when it does
is as important as catching a real defect — a critic that always finds something
is noise, and the loop it triggers wastes the user's time.

Call `submit_review` once."""


#: Workspace tools that CREATE or RUN things. Reading the workspace stays
#: allowed on every surface — knowing what is already there never causes the
#: wrong-surface failure, and removing it would break a follow-up turn on a
#: project that already exists.
_WORKSPACE_AUTHORING = {
    "workspace_write", "workspace_edit", "workspace_exec", "workspace_delete",
    "workspace_move", "workspace_package",
    # The dev-server tools belong to the workspace too. `preview_check` in
    # particular reads, by name, as "check the preview" — so on an artifact turn
    # the model called it on a rendered diagram, got "no dev server is running",
    # could not close the plan step that depended on it, and built the whole
    # diagram a second time. Offering a tool whose name invites the wrong
    # reading is a trap, and the surface filter is exactly where to remove it.
    "workspace_serve", "workspace_stop_server", "workspace_server_log",
    "preview_check",
}


def _is_workspace_authoring(name: str) -> bool:
    return name in _WORKSPACE_AUTHORING


#: What the model is told once the surface is settled. Short and imperative,
#: because this describes a constraint that has ALREADY been applied to its
#: toolset rather than a preference it is being asked to honour.
_SURFACE_DIRECTIVE = {
    "artifact": (
        "SURFACE: ARTIFACT. Deliver this as a rendered artifact inside the "
        "conversation, with a single create_* call (create_3d_experience, "
        "create_simulation, create_diagram, create_knowledge_graph, "
        "create_animation, create_html_page, generate_visual, generate_deck). "
        "Do NOT write project files and do NOT start a server — those tools are "
        "not available on this turn. Everything you need is already inlined: "
        "THREE, BABYLON, React and ReactFlow are globals, and the page has no "
        "network, so build geometry and colour in code."
    ),
    "workspace": (
        "SURFACE: WORKSPACE. Build this as real software in the project "
        "workspace: proper files, dependencies installed, tests written AND RUN, "
        "then packaged. Each command runs to completion, so verify with a script "
        "that exits rather than by starting a server."
    ),
    "analysis": (
        "SURFACE: ANALYSIS. Work on the user's data through run_analysis. Profile "
        "it first, then compute, then show the result and say what it means."
    ),
    "answer": (
        "SURFACE: ANSWER. This is a question to answer well, not a thing to "
        "build. Research it where that helps, and reach for a visual only where "
        "it makes the answer clearer."
    ),
}


def _continuation_brief(gaps: list[str]) -> str:
    """What the model is told when it stopped early."""
    lines = [
        "You are not finished. These are still outstanding:",
        "",
    ]
    lines += [f"  - {g}" for g in gaps[:8]]
    lines += [
        "",
        "IF ANY OF THESE IS ALREADY DONE, call `update_plan` to close it — do not "
        "do it again. Redoing finished work is the most expensive mistake available "
        "to you here.",
        "",
        "Then complete whatever genuinely remains. Do not summarise what you have "
        "done so far, do not ask whether to continue, and do not re-introduce the "
        "task — just do the remaining work. If something truly cannot be done, do "
        "the rest and then say plainly which part could not be done and why.",
    ]
    return "\n".join(lines)


def _repair_brief(defects: list[str]) -> str:
    lines = [
        "A review of your work found these problems:",
        "",
    ]
    lines += [f"  {i}. {d}" for i, d in enumerate(defects[:6], start=1)]
    lines += [
        "",
        "Fix them now. Change the actual work — the code, the artifact, the "
        "analysis — not just the description of it. When you are done, give the "
        "user the corrected result. Do not apologise and do not narrate the "
        "review; they only care about the outcome.",
    ]
    return "\n".join(lines)


def _compose(parts: list[str]) -> str:
    """Join what the model said across every pass into ONE answer.

    THE PROBLEM THIS SOLVES, AND WHY IT GOT WORSE THE DEEPER YOU SET THE DIAL

    A supervised turn generates several times: once per continuation pass, once
    more per repair round. Each pass produces prose, and the delivered answer
    was every pass concatenated. That is right in principle -- continuation
    passes are instructed to do the REMAINING work, so their text is
    incremental -- and wrong in practice, because models re-orient themselves
    when handed a conversation. A continuation pass reliably restates the
    problem, and a repair pass restates the parts that were already fine before
    describing what it changed.

    With one continuation the duplication is a paragraph. At Tapestry -- five
    continuations and two review-and-repair rounds -- it is the same material
    up to eight times over, often with the later statement contradicting the
    earlier one because the work changed underneath it. Which is exactly the
    shape of "the deep setting produces a worse answer than the quick one":
    more passes meant more repetition, and the mode that was supposed to be the
    most rigorous read as the most confused.

    Deduplicating by paragraph fixes it without discarding anything real. When
    a later pass repeats a paragraph, the LATER copy goes: the earlier one is
    where the reader first met the idea, and the reading order stays intact.
    Comparison is on normalised text -- case, whitespace and punctuation
    removed -- because models rarely repeat themselves byte for byte. Short
    paragraphs are exempt: "Done." and "Here is the code:" are legitimately
    repeated, and suppressing those removes signposts rather than duplication.
    """
    seen: set[str] = set()
    kept: list[str] = []
    for part in parts:
        if not part or not part.strip():
            continue
        for para in part.split("\n\n"):
            body = para.strip()
            if not body:
                continue
            key = _normalise(body)
            if len(key) >= 60:
                if key in seen:
                    continue
                seen.add(key)
            kept.append(body)
    return "\n\n".join(kept).strip()


def _normalise(text: str) -> str:
    """Case-, space- and punctuation-insensitive form, for repetition checks."""
    import re
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _string_list(raw: Any) -> list[str]:
    """Coerce whatever the model emitted into a list of clean strings.

    Necessary, not defensive. Given `steps: array of string`, these models emit
    strings — but also, depending on model and phrasing, a single newline-joined
    string, a JSON-encoded string, or objects with a `title`/`text`/`step` key.
    Rejecting those shapes would mean discarding a perfectly good plan over its
    packaging.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("["):
            try:
                return _string_list(json.loads(text))
            except (json.JSONDecodeError, ValueError):
                pass
        parts = [_strip_leading_number(p.strip(" -*\t")) for p in text.splitlines()]
        return [p for p in parts if p]
    if isinstance(raw, dict):
        raw = list(raw.values())
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            cleaned = item.strip()
        elif isinstance(item, dict):
            cleaned = str(
                item.get("title") or item.get("step") or item.get("text")
                or item.get("name") or item.get("description") or ""
            ).strip()
            detail = str(item.get("detail") or item.get("done_when") or "").strip()
            if cleaned and detail:
                cleaned = f"{cleaned} — {detail}"
        else:
            cleaned = str(item).strip()
        cleaned = _strip_leading_number(cleaned)
        if cleaned:
            out.append(cleaned)
    return out


def _strip_leading_number(text: str) -> str:
    """Drop a "1. " the model wrote into the step itself.

    The renderer numbers the steps, so a step whose text also starts with its
    number displays as "1. 1. Build the scene".
    """
    if not text[:1].isdigit():
        return text
    return text.lstrip("0123456789").lstrip(".) ").strip() or text
