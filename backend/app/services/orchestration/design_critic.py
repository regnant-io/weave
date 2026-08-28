"""Looking at the picture.

WHY A SEPARATE CRITIC, AND WHY IT USES A SCREENSHOT
---------------------------------------------------
The artifact gate answers one question well: does this page open without
throwing? That is necessary and it is not sufficient. The first simulation the
supervised loop produced passed every check and still drew its trajectory off
the top of the chart — arithmetically perfect, visually wrong, and completely
invisible to a checker that counts exceptions.

No amount of reading the SPEC catches that. The spec said `y = x·tan(θ) −
gx²/(2v²cos²θ)`, which is correct; whether the curve fits the window is a fact
about the rendered pixels, discoverable only by looking at them. So this module
sends the screenshot the probe already captured to a vision-capable model and
asks what is wrong with it.

WHAT IT IS ALLOWED TO SAY
-------------------------
Only things that are visible and wrong. A critic that returns taste
("consider a different palette") turns every artifact into three extra model
calls and teaches the model to ignore the channel. The prompt is written to make
"nothing is wrong" a comfortable answer, and the schema makes it a single word.

COST, AND WHY THIS IS OFF BY DEFAULT
------------------------------------
Every critique is a vision-model call on a JPEG. On a metered endpoint that is
real money and real latency, and most turns do not need it. It runs only at the
deepest effort level and only when a vision-capable model is actually available
— see `for_turn`, which returns None the rest of the time and costs nothing.
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger("weave.critic")

#: Vision model preference is separate from the turn's own model: the model
#: writing the scene need not be the one that looks at it, and the smallest
#: capable vision model is the right tool for "is anything cut off".
CRITIQUE_TOOL = {
    "name": "submit_visual_review",
    "description": "Record what is visibly wrong with this image. Call once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["good", "needs_work"],
                "description": "'good' if nothing is visibly wrong. This is a normal answer.",
            },
            "problems": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Only things VISIBLY WRONG, each naming what to change. Empty "
                    "when the verdict is 'good'."
                ),
            },
        },
        "required": ["verdict"],
    },
}

CRITIC_PROMPT = """\
You are looking at a screenshot of something that was just generated for a
student or researcher. It already runs without errors. Your only job is to say
whether it LOOKS right.

Report a problem only when you can SEE it:
- content cut off, clipped, or running outside its box
- a chart whose data does not fit its axes, or axes that do not fit the data
- text overlapping other text, or too small to read
- a large empty region where content should be
- something that is plainly blank, or has obviously failed to draw
- labels missing where they are needed to read the picture
- a layout that is broken rather than merely plain

Do NOT report:
- taste. Colour choices, font preferences, "it could be more modern".
- things you would add. Absence of a feature nobody asked for is not a defect.
- anything you are inferring rather than seeing.

Most generated images are fine. "good" is the expected answer and costs nothing
to give — say it whenever nothing on this list is visible. A critic that always
finds something is worse than no critic, because the work it triggers is
unpaid-for and the real problems get lost in it.

Call `submit_visual_review` exactly once."""


class DesignCritic:
    """Judges a rendered artifact by looking at it."""

    def __init__(self, engine, model: str) -> None:
        self.engine = engine
        self.model = model

    def __call__(self, screenshot_b64: str, title: str, tool: str) -> list[str]:
        """Return the visible problems, or an empty list."""
        if not screenshot_b64:
            return []

        found: dict = {}

        def executor(name: str, args: dict) -> dict:
            if name == "submit_visual_review":
                found.update(args or {})
                return {"status": "ok"}
            return {"status": "rejected", "error": "only submit_visual_review may be called"}

        what = f"This is “{title}”." if title else "This is a generated visual."
        try:
            self.engine.generate(
                system=CRITIC_PROMPT,
                messages=[{
                    "role": "user",
                    "content": f"{what} It was produced by `{tool}`. What is visibly "
                               "wrong with it?",
                    # Engine-neutral: Ollama consumes this natively and the
                    # Anthropic engine converts it to typed blocks.
                    "images": [screenshot_b64],
                }],
                tools=[CRITIQUE_TOOL],
                tool_executor=executor,
                tier="fast",
                on_event=None,
                effort="spool",
                model=self.model,
                max_iters=2,
            )
        except Exception as exc:  # noqa: BLE001 - a critique is never worth a failed turn
            log.info("visual critique unavailable (%s): %s", type(exc).__name__, exc)
            return []

        verdict = str(found.get("verdict") or "good").lower()
        if verdict == "good":
            return []
        problems = found.get("problems")
        if isinstance(problems, str):
            try:
                problems = json.loads(problems)
            except (json.JSONDecodeError, ValueError):
                problems = [problems]
        out = [str(p).strip() for p in (problems or []) if str(p).strip()]
        # `needs_work` with nothing to act on is not actionable; treat it as good
        # rather than sending the model back with "make it better".
        return [p for p in out if len(p) > 8][:5]


def for_turn(engine, effort: str | None) -> DesignCritic | None:
    """A critic, when this turn should pay for one.

    Returns None — and costs nothing — unless BOTH hold:

      * the user asked for the deepest effort level. Polishing is the thing
        Tapestry is for; adding a vision call to every quick answer would make
        the product slower at the exact moment people want it fast.
      * a vision-capable model is actually available. Asking a text-only model
        to look at an image gets a confident description of nothing.
    """
    if (effort or "").lower() != "tapestry":
        return None
    picker = getattr(engine, "vision_model", None)
    if not callable(picker):
        return None
    model = picker()
    if not model:
        return None
    return DesignCritic(engine, model)
