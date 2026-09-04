"""The `delegate` tool: hand one self-contained lookup to a scoped worker.

The mechanics live in services/orchestration/subagent.py, including why
delegates may only read. This module is the registration and the description
the model actually reads, which is the part that decides whether the capability
gets used well or at all.
"""
from __future__ import annotations

from .base import Tool, ToolContext, ToolRegistry


def _delegate(ctx: ToolContext, inp: dict) -> dict:
    runner = ctx.services.get("delegate")
    if runner is None:
        return {
            "status": "unavailable",
            "error": "delegation is not available on this turn",
        }
    return runner(
        task=str(inp.get("task") or ""),
        context=str(inp.get("context") or ""),
        expect=str(inp.get("expect") or ""),
    )


def register_all(reg: ToolRegistry) -> None:
    reg.register(Tool(
        name="delegate",
        # Concurrency is the second reason this tool exists. Four independent
        # lookups sent together take as long as the slowest one instead of the
        # sum of all four -- and delegates are read-only and never touch the
        # database, which is what makes running them at the same time safe.
        parallel_safe=True,
        description=(
            "Hand ONE self-contained lookup to a worker that reads the sources and "
            "reports back a short answer. Call it several times in one go for "
            "several independent questions — they run at the same time.\n\n"
            "USE IT when answering needs material you will not quote at length: "
            "comparing what four districts report, checking a claim against three "
            "papers, finding which file in a large codebase defines something. The "
            "worker reads everything; you get the finding. That keeps the sources "
            "out of this conversation, which is the point — pages of raw text you "
            "read once crowd out the rest of the chat for the rest of the session.\n\n"
            "DO NOT USE IT for the main question, for anything needing more than a "
            "few lookups, or for anything that makes or changes something. The "
            "worker can only READ (search the web, fetch a page, read the "
            "workspace, read a skill). It cannot write files, run code, produce "
            "visuals, or ask the user anything, and it cannot delegate further. "
            "One question per call, and it must be answerable without talking to "
            "you — the worker cannot come back with a clarification."
        ),
        input_schema={"type": "object", "properties": {
            "task": {
                "type": "string",
                "description": (
                    "The one question to answer, stated so it can be understood with "
                    "no other knowledge of this conversation. 'What does the 2022 NBS "
                    "report give as rural piped-water coverage for Dodoma?' — not "
                    "'check that one too'."
                ),
            },
            "context": {
                "type": "string",
                "description": (
                    "Anything from this conversation the worker needs and cannot see: "
                    "the user's actual subject, definitions already agreed, what has "
                    "already been ruled out. Keep it short; this is a briefing, not a "
                    "transcript."
                ),
            },
            "expect": {
                "type": "string",
                "description": (
                    "What you want back, concretely. 'The figure, the year, and the "
                    "table it came from' beats 'a summary' — you will be reading the "
                    "reply, not the sources, so ask for what you will need."
                ),
            },
        }, "required": ["task"]},
        execute=_delegate,
        trust_required="verified",
        requires_services=("delegate",),
    ))
