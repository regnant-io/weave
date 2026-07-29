"""Workspace tools — the assistant as a working developer.

These turn `services/workspace` into capabilities the model can call: create and
EDIT files, inspect the tree, run commands (installs, builds, tests), verify a
file actually parses, and package the result as a tarball.

Two design decisions are load-bearing:

  * `workspace_edit` exists so the model can change code in place. Without it a
    model rewrites whole files for one-line changes, which produces a directory
    full of near-duplicates and, on a long file, a truncated rewrite that
    destroys working code.

  * `workspace_verify` exists because a truncated or unbalanced generated file
    looks completely fine until someone opens it. Checking is milliseconds; the
    tool description tells the model to do it after every write.
"""
from __future__ import annotations

from .base import Tool, ToolContext, ToolRegistry


def _svc(ctx: ToolContext):
    return ctx.services.get("workspace")


def _project_id(ctx: ToolContext) -> str:
    return str(getattr(ctx.project, "id", "shared"))


def _unavailable() -> dict:
    return {"status": "unavailable",
            "message": "the developer workspace is not configured on this server"}


def _write_file(ctx: ToolContext, inp: dict) -> dict:
    svc = _svc(ctx)
    if svc is None:
        return _unavailable()
    result = svc.write_file(_project_id(ctx), inp.get("path", ""), inp.get("content", ""))
    if result.get("status") == "ok":
        ctx.progress("step_sub", {
            "text": f"{'Created' if result.get('created') else 'Updated'} {result['path']}",
            "detail": f"{result.get('bytes', 0)} bytes",
        })
        # Verify immediately. A model that forgets to check still cannot leave a
        # broken file behind unnoticed — the tool result says so.
        check = svc.verify_file(_project_id(ctx), result["path"])
        if check.get("status") == "ok" and check.get("valid") is False:
            result["verified"] = False
            result["verify_error"] = check.get("error")
            result["hint"] = ("The file you just wrote does not parse. Read it back and "
                              "fix it before continuing.")
        elif check.get("status") == "ok":
            result["verified"] = True
    return result


def _read_file(ctx: ToolContext, inp: dict) -> dict:
    svc = _svc(ctx)
    if svc is None:
        return _unavailable()
    return svc.read_file(
        _project_id(ctx), inp.get("path", ""),
        start=inp.get("start"), end=inp.get("end"),
    )


def _edit_file(ctx: ToolContext, inp: dict) -> dict:
    svc = _svc(ctx)
    if svc is None:
        return _unavailable()
    result = svc.edit_file(
        _project_id(ctx), inp.get("path", ""), inp.get("find", ""),
        inp.get("replace", ""), bool(inp.get("replace_all")),
    )
    if result.get("status") == "ok":
        ctx.progress("step_sub", {"text": f"Edited {result['path']}"})
        check = svc.verify_file(_project_id(ctx), result["path"])
        if check.get("status") == "ok" and check.get("valid") is False:
            result["verified"] = False
            result["verify_error"] = check.get("error")
            result["hint"] = "Your edit left the file unparseable. Read it back and repair it."
        elif check.get("status") == "ok":
            result["verified"] = True
    return result


def _list_tree(ctx: ToolContext, inp: dict) -> dict:
    svc = _svc(ctx)
    if svc is None:
        return _unavailable()
    return svc.list_tree(_project_id(ctx), inp.get("path", ""), int(inp.get("depth") or 4))


def _delete_path(ctx: ToolContext, inp: dict) -> dict:
    svc = _svc(ctx)
    if svc is None:
        return _unavailable()
    return svc.delete_path(_project_id(ctx), inp.get("path", ""))


def _move_path(ctx: ToolContext, inp: dict) -> dict:
    svc = _svc(ctx)
    if svc is None:
        return _unavailable()
    return svc.move_path(_project_id(ctx), inp.get("from", ""), inp.get("to", ""))


def _exec(ctx: ToolContext, inp: dict) -> dict:
    svc = _svc(ctx)
    if svc is None:
        return _unavailable()
    command = str(inp.get("command") or "")
    ctx.progress("step_sub", {"text": f"$ {command[:140]}"})
    res = svc.exec(_project_id(ctx), command, timeout=inp.get("timeout"), cancel=ctx.cancel)
    out = {
        "status": res.status, "exit_code": res.exit_code,
        "stdout": res.stdout, "stderr": res.stderr,
        "duration_ms": res.duration_ms,
    }
    if res.status == "timeout":
        out["hint"] = ("The command was killed at the time limit. Re-run it with a larger "
                       "`timeout`, or split the work into smaller steps.")
    return out


def _verify(ctx: ToolContext, inp: dict) -> dict:
    svc = _svc(ctx)
    if svc is None:
        return _unavailable()
    return svc.verify_file(_project_id(ctx), inp.get("path", ""))


def _package(ctx: ToolContext, inp: dict) -> dict:
    svc = _svc(ctx)
    if svc is None:
        return _unavailable()
    result = svc.package(_project_id(ctx), name=inp.get("name", ""), subdir=inp.get("path", ""))
    if result.get("status") == "ok":
        from .builtin import _emit_live
        _emit_live(ctx, result, "workspace_package")
    return result


def register_workspace_tools(reg: ToolRegistry) -> None:
    common = {"trust_required": "verified", "requires_services": ("workspace",)}

    reg.register(Tool(
        name="workspace_write",
        description=(
            "Create or overwrite a file in the project workspace — a persistent "
            "directory that survives across turns and chats. Use for source code, "
            "configs, assets and docs. Write the file COMPLETE: never abbreviate "
            "with '...' or 'rest unchanged'. To change part of an existing file "
            "use workspace_edit instead of rewriting it. The file is parse-checked "
            "automatically and the result tells you if it is broken."
        ),
        input_schema={"type": "object", "properties": {
            "path": {"type": "string",
                     "description": "Path relative to the workspace root, e.g. 'src/main.js'."},
            "content": {"type": "string", "description": "Full file contents."},
        }, "required": ["path", "content"]},
        execute=_write_file, **common,
    ))

    reg.register(Tool(
        name="workspace_edit",
        description=(
            "Replace an exact string inside an existing workspace file. Prefer this "
            "over rewriting a whole file: it is faster, cannot truncate the rest of "
            "the file, and keeps the diff small. `find` must appear exactly once — "
            "include surrounding lines to make it unique, or set replace_all."
        ),
        input_schema={"type": "object", "properties": {
            "path": {"type": "string"},
            "find": {"type": "string", "description": "Exact text to replace, including indentation."},
            "replace": {"type": "string", "description": "Replacement text."},
            "replace_all": {"type": "boolean", "description": "Replace every occurrence."},
        }, "required": ["path", "find", "replace"]},
        execute=_edit_file, **common,
    ))

    reg.register(Tool(
        name="workspace_read",
        description=(
            "Read a workspace file, optionally a line range. Read before editing so "
            "your `find` string matches the file exactly."
        ),
        input_schema={"type": "object", "properties": {
            "path": {"type": "string"},
            "start": {"type": "integer", "description": "First line (1-based)."},
            "end": {"type": "integer", "description": "Last line."},
        }, "required": ["path"]},
        execute=_read_file, **common,
    ))

    reg.register(Tool(
        name="workspace_list",
        description=(
            "List the workspace file tree. Call this first when returning to an "
            "existing project so you build on what is already there instead of "
            "recreating it."
        ),
        input_schema={"type": "object", "properties": {
            "path": {"type": "string", "description": "Subdirectory; omit for the root."},
            "depth": {"type": "integer", "description": "How many levels deep (default 4)."},
        }},
        execute=_list_tree, **common,
    ))

    reg.register(Tool(
        name="workspace_delete",
        description="Delete a file or directory from the workspace. Irreversible.",
        input_schema={"type": "object", "properties": {
            "path": {"type": "string"}}, "required": ["path"]},
        execute=_delete_path, **common,
    ))

    reg.register(Tool(
        name="workspace_move",
        description="Move or rename a file/directory inside the workspace.",
        input_schema={"type": "object", "properties": {
            "from": {"type": "string"}, "to": {"type": "string"},
        }, "required": ["from", "to"]},
        execute=_move_path, **common,
    ))

    reg.register(Tool(
        name="workspace_exec",
        description=(
            "Run a shell command in the workspace container (Debian, Node 20, "
            "Python 3, git, ffmpeg, ImageMagick). NETWORK IS AVAILABLE, so you can "
            "`npm install`, `pip install`, `git clone` and download assets or 3D "
            "models. Use it to install dependencies, build, and RUN TESTS — always "
            "run the tests you write. Long builds: pass a larger `timeout`."
        ),
        input_schema={"type": "object", "properties": {
            "command": {"type": "string", "description": "Shell command, run with bash -lc."},
            "timeout": {"type": "integer", "description": "Seconds to allow (default 180)."},
        }, "required": ["command"]},
        execute=_exec, **common,
    ))

    reg.register(Tool(
        name="workspace_verify",
        description=(
            "Check that a file actually parses — catches the truncated or "
            "unbalanced output that otherwise looks fine until someone opens it. "
            "Python and JSON are parsed exactly; JS/TS via `node --check`; other "
            "text files get a structural balance check."
        ),
        input_schema={"type": "object", "properties": {
            "path": {"type": "string"}}, "required": ["path"]},
        execute=_verify, **common,
    ))

    reg.register(Tool(
        name="workspace_package",
        description=(
            "Package the workspace (or one subdirectory) as a .tar.gz the user can "
            "download. Dependency directories and .git are excluded. Do this once "
            "the software builds and its tests pass."
        ),
        input_schema={"type": "object", "properties": {
            "name": {"type": "string", "description": "Archive name without extension."},
            "path": {"type": "string", "description": "Subdirectory to package; omit for all."},
        }},
        execute=_package, **common,
    ))
