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


def _grep(ctx: ToolContext, inp: dict) -> dict:
    svc = _svc(ctx)
    if svc is None:
        return _unavailable()
    return svc.grep(
        _project_id(ctx), str(inp.get("pattern") or ""),
        glob=str(inp.get("glob") or ""),
        case_sensitive=bool(inp.get("case_sensitive")),
        context=int(inp.get("context") or 0),
    )


def _glob(ctx: ToolContext, inp: dict) -> dict:
    svc = _svc(ctx)
    if svc is None:
        return _unavailable()
    return svc.glob_files(_project_id(ctx), str(inp.get("pattern") or "**/*"))


def _serve(ctx: ToolContext, inp: dict) -> dict:
    """Start a dev server and hand back a URL that actually works."""
    svc = _svc(ctx)
    if svc is None:
        return _unavailable()
    command = str(inp.get("command") or "").strip()
    if not command:
        return {"status": "error", "error": "a command is required, e.g. 'npm run dev'"}
    try:
        port = int(inp.get("port") or 5173)
    except (TypeError, ValueError):
        return {"status": "error", "error": "port must be a number"}

    ctx.progress("step_sub", {"text": f"Starting {command[:90]} on :{port}"})
    out = svc.serve(_project_id(ctx), command, port,
                    wait_seconds=int(inp.get("wait") or 45))
    if out.get("status") != "ok":
        return out

    # Tell the client so it can open the preview panel. The URL is on the host
    # loopback, which is where the USER's browser can reach it.
    ctx.progress("preview", {
        "url": out.get("url", ""),
        "port": port,
        "command": command,
    })
    out["note"] = (
        "The server is up and the user can see it in the preview panel. Now CHECK "
        "IT: call `preview_check` to open the running app in a real browser and "
        "get back its console errors and a screenshot. A server that starts is not "
        "an app that works."
    )
    return out


def _stop_server(ctx: ToolContext, _inp: dict) -> dict:
    svc = _svc(ctx)
    if svc is None:
        return _unavailable()
    out = svc.stop_server(_project_id(ctx))
    ctx.progress("preview", {"url": "", "stopped": True})
    return out


def _server_log(ctx: ToolContext, inp: dict) -> dict:
    svc = _svc(ctx)
    if svc is None:
        return _unavailable()
    return svc.server_log(_project_id(ctx), lines=int(inp.get("lines") or 200))


def _preview_check(ctx: ToolContext, inp: dict) -> dict:
    """Open the running dev server in a real browser and report what happened.

    This is the workspace counterpart of the artifact gate. Building a web app
    and never loading it is the same failure as rendering a scene and never
    opening it — the code looks right, the server said "ready in 340ms", and the
    page is blank because a module failed to resolve.

    Browserless reaches the server by CONTAINER NAME on the Docker network. The
    host-loopback URL the user opens is meaningless from inside another
    container, and using it here is the obvious mistake that makes this tool
    report "connection refused" for a perfectly healthy app.
    """
    svc = _svc(ctx)
    if svc is None:
        return _unavailable()
    status = svc.server_status(_project_id(ctx))
    if not status.get("running"):
        return {
            "status": "error",
            "error": (
                "no dev server is running. This tool checks a web app you started "
                "with `workspace_serve` — it is not for artifacts. An artifact you "
                "rendered has ALREADY been opened in a browser and verified; if you "
                "want to check one yourself, use `verify_artifact`."
            ),
        }

    path = str(inp.get("path") or "/")
    if not path.startswith("/"):
        path = "/" + path
    target = status["internal_url"].rstrip("/") + path

    from ..render.probe import get_probe
    ctx.progress("step_sub", {"text": f"Opening {path} in a browser"})
    run = get_probe().run_url(target, heavy=True)

    if not run.available:
        return {"status": "ok", "checked": target, "executed": False,
                "note": run.note or "the browser pool is not available"}

    errors, warnings = list(run.errors), list(run.warnings)

    log = svc.server_log(_project_id(ctx), lines=40).get("log", "")
    return {
        "status": "ok",
        "checked": target,
        "executed": True,
        "ok": not errors,
        "errors": errors[:10],
        "warnings": warnings[:6],
        "server_log": log[-2000:],
        "note": ("The page loads and renders without errors."
                 if not errors else
                 "The running app is BROKEN. Fix these and check again before "
                 "telling the user it works."),
    }


def _git(ctx: ToolContext, inp: dict) -> dict:
    """Version control inside the workspace.

    A long agentic run makes dozens of edits, and until now there was no way to
    see what changed or to undo a pass that made things worse — the only records
    were the files as they ended up. Committing at each checkpoint turns the run
    into something reviewable, and `revert` makes a bad pass recoverable instead
    of terminal.
    """
    svc = _svc(ctx)
    if svc is None:
        return _unavailable()
    action = str(inp.get("action") or "status").lower()
    pid = _project_id(ctx)

    # Identity and an initial commit are set up on first use rather than asked
    # for: a model that has to remember to `git init` will forget, and the
    # failure surfaces much later as "not a git repository".
    setup = (
        "git rev-parse --git-dir >/dev/null 2>&1 || { "
        "  git init -q && "
        "  git config user.email weave@local && "
        "  git config user.name Weave && "
        "  printf 'node_modules/\\n.cache/\\n.weave/\\ndist/\\n.next/\\n__pycache__/\\n' > .gitignore; "
        "}"
    )

    if action == "commit":
        message = str(inp.get("message") or "checkpoint").replace("'", "")[:200]
        cmd = (f"{setup} && git add -A && "
               f"(git diff --cached --quiet && echo 'nothing to commit' || "
               f"git commit -q -m '{message}' && git log --oneline -1)")
    elif action == "log":
        cmd = f"{setup} && git log --oneline -n {int(inp.get('limit') or 15)} || true"
    elif action == "diff":
        ref = str(inp.get("ref") or "HEAD").replace("'", "")[:80]
        cmd = f"{setup} && git --no-pager diff --stat {ref} && git --no-pager diff {ref} | head -c 12000"
    elif action == "revert":
        ref = str(inp.get("ref") or "HEAD").replace("'", "")[:80]
        cmd = f"{setup} && git reset --hard {ref} && git log --oneline -1"
    else:
        cmd = f"{setup} && git status --short && echo '---' && git log --oneline -n 5 || true"

    res = svc.exec(pid, cmd, timeout=90, cancel=ctx.cancel)
    return {
        "status": "ok" if res.status == "ok" else "error",
        "action": action,
        "output": (res.stdout or "")[:12000],
        "error": (res.stderr or "")[:1000] if res.status != "ok" else "",
    }


def register_workspace_tools(reg: ToolRegistry) -> None:
    common = {"trust_required": "verified", "requires_services": ("workspace",)}

    reg.register(Tool(
        name="workspace_serve",
        description=(
            "Start a dev server (`npm run dev`, `vite`, `python3 -m http.server`) "
            "and get back a URL the user can actually open — the app appears in a "
            "live preview panel beside the chat. The command runs in the "
            "background and keeps running between turns, so this is how you show "
            "someone a working web app rather than a tarball. Ports 5173, 3000, "
            "8000 and 8080 are published; bind to 0.0.0.0, not localhost, or "
            "nothing outside the container can reach it. Returns once the port is "
            "genuinely accepting connections, so a URL you get back is a URL that "
            "works. ALWAYS follow it with `preview_check`."
        ),
        input_schema={"type": "object", "properties": {
            "command": {"type": "string",
                        "description": "e.g. 'npm run dev -- --host 0.0.0.0 --port 5173'"},
            "port": {"type": "integer", "description": "5173, 3000, 8000 or 8080."},
            "wait": {"type": "integer", "description": "Seconds to wait for it (default 45)."},
        }, "required": ["command", "port"]},
        execute=_serve, **common,
    ))

    reg.register(Tool(
        name="preview_check",
        description=(
            "Open the RUNNING dev server in a real headless browser and report what "
            "actually happened: uncaught exceptions, console errors, whether "
            "anything rendered, plus the server's own log. This is how you find out "
            "your app works instead of assuming it. A build that compiles and a "
            "page that renders are different claims, and only this one tests the "
            "second. Run it after every significant change."
        ),
        input_schema={"type": "object", "properties": {
            "path": {"type": "string", "description": "Route to open, default '/'."},
            "note": {"type": "string"},
        }},
        execute=_preview_check, **common,
    ))

    reg.register(Tool(
        name="workspace_stop_server",
        description="Stop the running dev server. Use when switching to a different "
                    "command or when the app is finished.",
        input_schema={"type": "object", "properties": {}},
        execute=_stop_server, **common,
    ))

    reg.register(Tool(
        name="workspace_server_log",
        description="Read the dev server's output. The first place to look when a "
                    "page is blank or a request 500s.",
        input_schema={"type": "object", "properties": {
            "lines": {"type": "integer", "description": "How many lines (default 200)."},
        }},
        execute=_server_log, **common,
    ))

    reg.register(Tool(
        name="workspace_git",
        description=(
            "Version control for the workspace. `commit` a checkpoint after each "
            "working milestone so the user can see the history and you can undo a "
            "change that made things worse; `status`, `log` and `diff` to see what "
            "changed; `revert` to roll back to a commit. The repository and a "
            "sensible .gitignore are created on first use. Commit BEFORE a risky "
            "change, not only after a successful one."
        ),
        input_schema={"type": "object", "properties": {
            "action": {"type": "string", "enum": ["status", "commit", "log", "diff", "revert"]},
            "message": {"type": "string", "description": "Commit message."},
            "ref": {"type": "string", "description": "Commit ref for diff/revert."},
            "limit": {"type": "integer"},
        }, "required": ["action"]},
        execute=_git, **common,
    ))

    reg.register(Tool(
        name="workspace_grep",
        parallel_safe=True,
        description=(
            "Search the project workspace for a regular expression and get back the "
            "matching lines with their file and line number. This is how you find "
            "where something is defined or used WITHOUT reading whole files into "
            "context — use it before workspace_read, not instead of it. Dependency "
            "and build directories (node_modules, .git, .venv, dist) are skipped. "
            "Narrow with `glob` when you know the file type."
        ),
        input_schema={"type": "object", "properties": {
            "pattern": {"type": "string", "description": "Python regular expression."},
            "glob": {"type": "string",
                     "description": "Restrict to matching paths, e.g. '*.py' or 'src/**/*.ts'."},
            "case_sensitive": {"type": "boolean", "description": "Default false."},
            "context": {"type": "integer",
                        "description": "Lines of surrounding context per match (0-5)."},
            "note": {"type": "string"},
        }, "required": ["pattern"]},
        execute=_grep, **common,
    ))

    reg.register(Tool(
        name="workspace_glob",
        parallel_safe=True,
        description=(
            "List workspace files matching a glob pattern ('**/*.py', 'src/*.ts'), "
            "with their sizes. Returns paths only. Use it to orient yourself in a "
            "project whose layout you do not know, then read or grep the few files "
            "that matter."
        ),
        input_schema={"type": "object", "properties": {
            "pattern": {"type": "string", "description": "Glob, default '**/*'."},
            "note": {"type": "string"},
        }},
        execute=_glob, **common,
    ))

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
        parallel_safe=True,
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
        parallel_safe=True,
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
