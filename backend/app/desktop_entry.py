"""Entrypoint for the frozen local desktop service."""
from __future__ import annotations

import os
import sys


def main() -> None:
    # Before anything can start a child process: no console windows popping
    # up outside the app for PowerShell, npm, git or the sandbox.
    from app.windows_console import hide_child_consoles
    hide_child_consoles()

    if len(sys.argv) >= 2 and sys.argv[1] == "weave-python":
        import runpy

        tool_dir = os.environ.get("WEAVE_DESKTOP_TOOL_DIR")
        if tool_dir:
            shim = "python.cmd" if os.name == "nt" else "python"
            sys.executable = os.path.join(tool_dir, shim)

        args = sys.argv[2:]
        # Workspace tooling commonly asks for a version or uses -u/-B for
        # non-interactive scripts. These switches must not become filenames.
        if args and args[0] in {"-V", "--version", "-VV"}:
            print("Python " + (sys.version if args[0] == "-VV" else sys.version.split()[0]))
            return
        while args and args[0] in {"-u", "-B"}:
            option = args.pop(0)
            if option == "-B":
                sys.dont_write_bytecode = True
            else:
                for stream in (sys.stdout, sys.stderr):
                    if hasattr(stream, "reconfigure"):
                        stream.reconfigure(write_through=True)
        # Match CPython's script/module import path. Frozen Python otherwise
        # cannot import another source module from the workspace being tested.
        source_dir = (os.path.dirname(os.path.abspath(args[0])) if args
                      and not args[0].startswith("-") else os.getcwd())
        if source_dir not in sys.path:
            sys.path.insert(0, source_dir)
        if not args:
            print("usage: python -c CODE | -m MODULE | FILE [args]", file=sys.stderr)
            raise SystemExit(2)
        if args[0] == "-c" and len(args) >= 2:
            sys.argv = ["-c", *args[2:]]
            exec(compile(args[1], "<string>", "exec"), {"__name__": "__main__"})
        elif args[0] == "-m" and len(args) >= 2:
            sys.argv = [args[1], *args[2:]]
            runpy.run_module(args[1], run_name="__main__", alter_sys=True)
        elif args[0].startswith("-"):
            print(f"unsupported Python option: {args[0]}", file=sys.stderr)
            raise SystemExit(2)
        else:
            sys.argv = [args[0], *args[1:]]
            runpy.run_path(args[0], run_name="__main__")
        return

    if len(sys.argv) >= 3 and sys.argv[1] == "weave-sandbox":
        from app.services.sandbox.runner import main as run_sandbox

        sys.argv = [sys.argv[0], *sys.argv[2:]]
        raise SystemExit(run_sandbox())

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=os.environ.get("WEAVE_BIND_HOST", "127.0.0.1"),
        port=int(os.environ.get("WEAVE_BIND_PORT", "8000")),
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
