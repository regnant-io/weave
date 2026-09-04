"""Tools for discovering and loading skills.

Two tools, deliberately separate. `list_skills` is cheap and returns names and
one-line descriptions only; `read_skill` is what actually spends tokens, and it
is called once for the one skill that applies. Collapsing them into a single
"give me every skill" tool would put the whole library in context on every task
that needed one line of it.
"""
from __future__ import annotations

from .base import Tool, ToolContext, ToolRegistry


def _service(ctx: ToolContext):
    return ctx.services.get("skills")


def _list_skills(ctx: ToolContext, inp: dict) -> dict:
    svc = _service(ctx)
    if svc is None:
        return {"status": "unavailable", "message": "the skill library is not loaded"}
    found = svc.list(str(inp.get("query") or ""))
    return {
        "status": "ok",
        "count": len(found),
        "skills": found,
        "note": "Call read_skill with a name before following one — the description "
                "is not the procedure.",
    }


def _read_skill(ctx: ToolContext, inp: dict) -> dict:
    svc = _service(ctx)
    if svc is None:
        return {"status": "unavailable", "message": "the skill library is not loaded"}
    name = str(inp.get("name") or "").strip()
    if not name:
        return {"status": "error", "error": "name is required"}
    skill = svc.read(name)
    if skill is None:
        return {
            "status": "error",
            "error": f"no skill called '{name}'",
            "available": svc.names(),
        }
    return {
        "status": "ok",
        "name": skill.name,
        "title": skill.title,
        "description": skill.description,
        "body": skill.body,
    }


def register_skill_tools(reg: ToolRegistry) -> None:
    reg.register(Tool(
        name="list_skills",
        parallel_safe=True,
        description=(
            "List the skills available to you: worked procedures for the tasks "
            "students and researchers actually bring, and for getting the most out "
            "of Weave's own capabilities. Returns names and one-line descriptions "
            "only — cheap to call. Do this whenever a task is substantial and you "
            "are not certain of the best approach. Optionally pass a `query` to "
            "rank by relevance."
        ),
        input_schema={"type": "object", "properties": {
            "query": {"type": "string",
                      "description": "Topic words to rank by, e.g. 'regression survey'."},
            "note": {"type": "string"},
        }},
        execute=_list_skills, trust_required="anonymous", requires_services=("skills",),
    ))

    reg.register(Tool(
        name="read_skill",
        parallel_safe=True,
        description=(
            "Load a skill's full procedure by name. YOU MUST READ A SKILL BEFORE "
            "FOLLOWING IT — the name and description tell you almost nothing, and "
            "the body is where the decisions that matter are. Never claim to have "
            "applied a skill you have not read. Call list_skills first if you do "
            "not know the exact name."
        ),
        input_schema={"type": "object", "properties": {
            "name": {"type": "string", "description": "Skill name from list_skills."},
            "note": {"type": "string"},
        }, "required": ["name"]},
        execute=_read_skill, trust_required="anonymous", requires_services=("skills",),
    ))
