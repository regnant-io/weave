"""The artifact gate: nothing ships until it has been opened.

THE PROBLEM THIS SOLVES
-----------------------
The single most damaging behaviour in the old loop was emit-and-continue. A tool
returned `status: "ok"` the moment the render service accepted a payload, the
artifact was pushed into the transcript immediately, and the model moved on to
write its closing paragraph. Whether the page actually opened was discovered by
the user, minutes later, looking at a black rectangle.

Every layer was individually reasonable. `render_custom` succeeded — it did
produce a file. `lintHtml` passed — the document was well-formed. The model was
told to call `verify_artifact` and, being a model, sometimes did not. The
failure lived in the space between them: nothing in the system was *obliged* to
find out whether the thing worked.

So this module makes it obligatory, and takes it away from the model's
discretion entirely. Every artifact-producing tool call is intercepted:

  1. The artifact is NOT released into the transcript when the tool returns.
  2. It is linted statically and then EXECUTED in a real browser.
  3. If it is broken, the tool result the model receives is not "ok" — it is a
     numbered list of what went wrong and an instruction to fix it. The model
     cannot proceed to its summary believing the work is done, because from
     where it sits, the tool failed.
  4. Only a clean artifact is released to the user.

REPAIR BUDGET
-------------
Three attempts per artifact, then it is released with its defects recorded and
the model is told to say plainly what still does not work. The budget exists
because an unbounded repair loop against a model that cannot fix the problem is
just a slower way to fail, and because a broken artifact plus an honest
description of how it is broken is far more useful than silence.

WHAT IS DELIBERATELY NOT DONE HERE
----------------------------------
The gate never rewrites the model's code. A silent fix produces an artifact the
model does not know the shape of, which then diverges from what it tells the
user it built. The gate reports; the model repairs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger("weave.verify")

#: Tools whose output is a page a human will look at. Each is gated.
#:
#: `generate_visual` renders a Vega-Lite spec to SVG server-side — there is no
#: page and no script, so there is nothing a browser could tell us that the
#: renderer did not already reject. It is deliberately absent.
GATED_TOOLS: dict[str, str] = {
    "create_3d_experience": "heavy",
    "generate_3d": "heavy",
    "create_simulation": "heavy",
    "render_custom": "heavy",
    "create_knowledge_graph": "heavy",
    "create_html_page": "light",
    "create_animation": "light",
    "create_diagram": "light",
    "generate_deck": "light",
    "update_visual": "heavy",
}

#: How many times one artifact may be sent back for repair before it is released
#: with its defects on the record.
MAX_REPAIRS = 3


@dataclass
class Verdict:
    """The outcome of gating one tool call."""

    checked: bool = False           # did we actually get to run a check
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    attempt: int = 1
    exhausted: bool = False         # budget spent; released with defects
    screenshot_key: str = ""        # storage key of the captured preview
    summary: str = ""
    duration_ms: int = 0
    #: Design problems found by LOOKING at the render. Distinct from `errors`:
    #: the page works, it just is not good enough yet. See `ArtifactGate.polish`.
    polish_notes: list[str] = field(default_factory=list)

    @property
    def needs_polish(self) -> bool:
        return bool(self.polish_notes) and self.ok and not self.exhausted

    @property
    def released(self) -> bool:
        """Whether the artifact should reach the user this time round."""
        if self.needs_polish:
            return False
        return self.ok or self.exhausted


class ArtifactGate:
    """Per-turn verification state. One instance per turn."""

    def __init__(self, project_id: str, polish=None) -> None:
        """`polish(screenshot_b64, title, tool) -> list[str]`, or None.

        Optional because LOOKING at the render costs a vision-model call, which
        is not worth it on every turn. When supplied, an artifact that renders
        without errors is still not finished until it also looks right — see
        `check`. The gate does not know how the critique is produced; that keeps
        every LLM concern out of this module.
        """
        self.project_id = str(project_id or "shared")
        self.polish = polish
        #: attempts keyed by artifact identity, so a model that keeps rewriting
        #: THE SAME broken scene is bounded, while a turn producing five
        #: different artifacts gets a full budget for each.
        self._attempts: dict[str, int] = {}

    # -- public ------------------------------------------------------------

    def gates(self, tool_name: str) -> bool:
        return tool_name in GATED_TOOLS

    def check(self, tool_name: str, tool_input: dict, result: dict) -> Verdict:
        """Lint and execute whatever this tool produced.

        Returns a Verdict. The caller decides what to do with it; this method
        has no side effects on the transcript.
        """
        if result.get("status") not in {"ok", "success"}:
            # The tool itself failed. The model already has that error; running
            # a browser against nothing would only add noise.
            return Verdict(checked=False, ok=False, summary="tool failed before rendering")

        html = self._extract_html(result)
        if not html:
            return Verdict(checked=False, ok=True, summary="nothing to check")

        key = self._identity(tool_name, tool_input, result)
        attempt = self._attempts.get(key, 0) + 1
        self._attempts[key] = attempt

        errors: list[str] = []
        warnings: list[str] = []
        screenshot_key = ""
        duration = 0

        # 1. Static pass first — it is free, and it catches the class of error a
        #    browser reports only as a vague blank page.
        from ..render import get_render

        client = get_render()
        try:
            lint = client.verify_html(html)
            errors.extend(str(e) for e in (lint.get("errors") or []))
            warnings.extend(str(w) for w in (lint.get("warnings") or []))
        except Exception as exc:  # noqa: BLE001 - a lint outage must not block
            log.debug("static lint unavailable: %s", exc)

        # 2. Execute it. This is the check that catches the errors that matter.
        from ..render.probe import get_probe

        probe = get_probe()
        run = probe.run(html, heavy=GATED_TOOLS.get(tool_name) == "heavy")
        duration = run.duration_ms
        if run.available:
            errors.extend(run.errors)
            warnings.extend(run.warnings)
            if run.screenshot_b64:
                screenshot_key = self._store_preview(run.screenshot_b64, tool_name)

        errors = _dedupe(errors)[:12]
        warnings = _dedupe(warnings)[:8]
        ok = not errors
        exhausted = (not ok) and attempt >= MAX_REPAIRS

        # LOOK at it, once it is known to work.
        #
        # The gate proves a page renders; it cannot tell whether it renders
        # WELL. The first simulation this loop produced passed every check and
        # still drew its trajectory off the top of the chart — arithmetically
        # perfect, visually wrong. Errors and ugliness are different questions,
        # and only one of them can be answered by counting exceptions.
        #
        # Skipped on the last attempt: sending the model back to polish
        # something it can no longer resubmit is a round trip for nothing.
        polish_notes: list[str] = []
        if ok and self.polish and run.screenshot_b64 and attempt < MAX_REPAIRS:
            try:
                polish_notes = [n for n in self.polish(
                    run.screenshot_b64, str(tool_input.get("title") or ""), tool_name,
                ) if n][:5]
            except Exception as exc:  # noqa: BLE001 - never block on a critique
                log.debug("visual critique failed: %s", exc)

        return Verdict(
            checked=True,
            ok=ok,
            errors=errors,
            warnings=warnings,
            attempt=attempt,
            exhausted=exhausted,
            screenshot_key=screenshot_key,
            duration_ms=duration,
            polish_notes=polish_notes,
            summary=(
                ("renders clean · polishing" if polish_notes else "renders clean") if ok
                else f"{len(errors)} problem{'s' if len(errors) != 1 else ''}"
                     f" · attempt {attempt}/{MAX_REPAIRS}"
            ),
        )

    # -- shaping the model's view of the failure ---------------------------

    @staticmethod
    def apply(result: dict, verdict: Verdict, tool_name: str) -> dict:
        """Rewrite a tool result so the model sees the truth about its output.

        This is the load-bearing part. A model that receives `{"status": "ok"}`
        has been told its work is finished, and no amount of system-prompt
        exhortation reliably overrides a tool result. So a broken artifact comes
        back as a FAILED tool call, with the specific defects and an explicit
        next action.
        """
        if not verdict.checked:
            return result

        out = dict(result)
        out["verification"] = {
            "ran": True,
            "ok": verdict.ok,
            "errors": verdict.errors,
            "warnings": verdict.warnings,
            "attempt": verdict.attempt,
            "attempts_remaining": max(0, MAX_REPAIRS - verdict.attempt),
        }

        if verdict.needs_polish:
            # It works. It is not good enough yet.
            #
            # Deliberately NOT a hard failure — nothing is broken, so the
            # language is about improvement rather than repair. But the artifact
            # is still withheld, because releasing it and asking for a better
            # one afterwards produces two versions in the transcript and leaves
            # the reader to work out which is current.
            out["status"] = "needs_polish"
            out["verified"] = True
            out["verification"]["polish"] = verdict.polish_notes
            out.pop("output_files", None)
            out["error"] = _polish_brief(tool_name, verdict)
            return out

        if verdict.ok:
            out["status"] = "ok"
            out["verified"] = True
            if verdict.warnings:
                out["note"] = ("It opens and renders. Worth a look before you move on: "
                               + "; ".join(verdict.warnings[:3]))
            else:
                out["note"] = "Verified: the page opens and renders without errors."
            return out

        if verdict.exhausted:
            # Released, but honestly. The model must not describe this as working.
            out["status"] = "ok"
            out["verified"] = False
            out["note"] = (
                "RELEASED WITH KNOWN DEFECTS after "
                f"{verdict.attempt} repair attempts. It still fails: "
                + "; ".join(verdict.errors[:4])
                + ". Show it to the user anyway, but say plainly and specifically "
                  "what does not work. Do NOT describe it as finished or working."
            )
            return out

        # The important case: make the model believe (correctly) that it failed.
        out["status"] = "needs_repair"
        out["verified"] = False
        out.pop("output_files", None)   # nothing was released; do not imply it was
        out["error"] = _repair_brief(tool_name, verdict)
        return out

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _extract_html(result: dict) -> str:
        """Pull the page out of whatever the tool returned."""
        from ...storage import storage

        for f in result.get("output_files") or []:
            if f.get("mime") != "text/html":
                continue
            key = f.get("s3_key")
            if not key:
                continue
            try:
                return storage.get_bytes(key).decode("utf-8", "replace")
            except Exception as exc:  # noqa: BLE001
                log.debug("could not read artifact %s: %s", key, exc)
        # Some renderers hand the page back inline as well.
        html = result.get("html")
        return html if isinstance(html, str) else ""

    def _identity(self, tool_name: str, tool_input: dict, result: dict) -> str:
        """A stable key for 'the same artifact, being retried'.

        Prefers the visual id, because that is what `update_visual` reuses. Falls
        back to the title, then the tool name — deliberately coarse, so repeated
        attempts at one thing are counted together rather than each getting a
        fresh budget under a slightly different title.
        """
        vid = result.get("visual_id") or tool_input.get("visual_id")
        if vid:
            return f"{self.project_id}:{vid}"
        title = str(tool_input.get("title") or "").strip().lower()
        return f"{self.project_id}:{tool_name}:{title}"

    @staticmethod
    def _store_preview(b64: str, tool_name: str) -> str:
        """Persist the screenshot so the UI can show a poster frame.

        A 3D scene costs a WebGL context to display; a transcript with a dozen
        of them cannot mount them all. A real screenshot of the real thing is
        the right placeholder — and it is proof the page rendered.
        """
        import base64
        import uuid

        from ...storage import storage

        try:
            data = base64.b64decode(b64)
        except Exception:  # noqa: BLE001
            return ""
        if not data:
            return ""
        key = f"render/preview_{uuid.uuid4().hex[:8]}_{tool_name}.jpg"
        try:
            storage.put_bytes(key, data)
        except Exception as exc:  # noqa: BLE001
            log.debug("could not store preview: %s", exc)
            return ""
        return key


def _repair_brief(tool_name: str, verdict: Verdict) -> str:
    """The message the model reads when its artifact failed.

    Written as an instruction, not a description. A model handed a list of
    symptoms will sometimes acknowledge them and carry on; a model handed
    "fix these and call the tool again" repairs.
    """
    lines = [
        f"This artifact does NOT work. It was opened in a real browser and it failed. "
        f"(attempt {verdict.attempt} of {MAX_REPAIRS})",
        "",
        "What went wrong:",
    ]
    lines += [f"  {i}. {e}" for i, e in enumerate(verdict.errors[:8], start=1)]
    if verdict.warnings:
        lines.append("")
        lines.append("Also worth fixing:")
        lines += [f"  - {w}" for w in verdict.warnings[:4]]
    lines += [
        "",
        "It has NOT been shown to the user. Fix the cause and call "
        f"`{tool_name}` again with the corrected version.",
    ]
    if any("did not return" in e.lower() for e in verdict.errors):
        lines.append(
            "Hint: the scene function must END with `return scene;` — creating the "
            "scene is not enough."
        )
    if any("no visible content" in e.lower() or "rendered nothing" in e.lower()
           for e in verdict.errors):
        lines.append(
            "Hint: a page that throws nothing and draws nothing usually means the "
            "setup code never ran, or it drew into an element that is not in the "
            "document. Check that a camera and a light exist for a 3D scene."
        )
    return "\n".join(lines)


def _polish_brief(tool_name: str, verdict: Verdict) -> str:
    """What the model reads when its artifact works but is not good enough.

    The tone matters. A repair brief says "this is broken"; that is true of a
    scene that throws and false of a chart whose axis is badly chosen, and using
    the same language for both teaches the model to treat design notes as noise.
    """
    lines = [
        f"This renders correctly, but it is not finished. Someone looked at the "
        f"actual picture it produces and found these problems "
        f"(pass {verdict.attempt} of {MAX_REPAIRS}):",
        "",
    ]
    lines += [f"  {i}. {n}" for i, n in enumerate(verdict.polish_notes, start=1)]
    lines += [
        "",
        "It has NOT been shown to the user yet. Improve it and call "
        f"`{tool_name}` again. Change the SPEC — the layout, the ranges, the "
        "labels, the amount on screen — not the wording of your description of "
        "it. If you genuinely disagree with one of these, fix the others and "
        "say why you left it.",
    ]
    return "\n".join(lines)


def _dedupe(items: list[str]) -> list[str]:
    """Preserve order, drop repeats — a render loop emits the same error 60x/s."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip()[:200]
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out
