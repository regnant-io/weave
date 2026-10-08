"""Run a project's own verification: the definition of "the code works".

WHY THIS IS A TOOL AND NOT AN INSTRUCTION
-----------------------------------------
The system prompt has always said "run the tests you write". Models comply
unevenly. They run `node index.js` and call that a test, forget the type
checker exists, or run the build before installing. Worse, the supervisor had
no way to know whether code was verified, so it asked an LLM critic to guess
from a log, on every build request.

This module makes verification deterministic. It reads the project's
manifests, derives the checks the project itself declares (install,
typecheck, lint, test, build, in that order), runs them fail-fast, and returns
a structured report. The supervisor treats "source changed since the last
passing check" as unfinished work, which it can observe instead of guess.

Detection is deliberately conservative. A check is only run when the project
declares it (a `test` script, a tsconfig with TypeScript installed, a tests
directory with pytest configured). Inventing checks the author never wrote
produces failures nobody can act on.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

#: package.json scripts that never exit, or that change the world, and so are
#: never run as a check.
_LONG_RUNNING = re.compile(r"\b(dev|start|serve|preview|watch)\b", re.I)
#: Script bodies that start a watcher even when named "test".
_WATCH_FLAGS = re.compile(r"--watch\b|\bwatch\b(?!-)", re.I)

#: Order matters: cheapest and most diagnostic first, so a type error is
#: reported as a type error rather than as a failed build three minutes later.
_SCRIPT_ORDER = (
    ("typecheck", ("typecheck", "type-check", "types", "check-types", "tsc")),
    ("lint", ("lint",)),
    ("test", ("test", "test:unit", "tests")),
    ("build", ("build",)),
)

#: Output markers meaning "this check could not run here", as opposed to "it
#: ran and failed". Reported as skipped so a missing tool is not read as broken
#: code the model must fix.
_UNAVAILABLE = re.compile(
    r"No module named pytest|is not recognized as (?:the name of )?a cmdlet|"
    r"is not recognized as an internal or external command|command not found|"
    r"cannot find the path|ENOENT.*spawn", re.I)


@dataclass
class Check:
    name: str
    command: str
    timeout: int = 600
    #: A failed install makes every later check meaningless.
    required: bool = True


@dataclass
class CheckOutcome:
    name: str
    command: str
    status: str               # passed | failed | skipped | timeout
    exit_code: int = 0
    duration_ms: int = 0
    output: str = ""


@dataclass
class CheckReport:
    root: str
    detected: list[str] = field(default_factory=list)
    outcomes: list[CheckOutcome] = field(default_factory=list)
    note: str = ""

    @property
    def ran(self) -> list[CheckOutcome]:
        return [o for o in self.outcomes if o.status != "skipped"]

    @property
    def passed(self) -> bool:
        return bool(self.ran) and all(o.status == "passed" for o in self.ran)

    def as_result(self) -> dict:
        failed = next((o for o in self.outcomes if o.status in {"failed", "timeout"}), None)
        if not self.outcomes:
            summary = self.note or "no checks were detected for this project"
        elif failed:
            summary = f"{failed.name} failed (exit {failed.exit_code})"
        elif self.passed:
            summary = "all checks passed: " + ", ".join(o.name for o in self.ran)
        else:
            summary = "no check could run in this environment"
        return {
            # `ok` when every check that could run passed. A project with no
            # checks is reported as such and never as passing.
            "status": "ok" if self.passed else ("error" if failed else "unverified"),
            "passed": self.passed,
            "summary": summary,
            "root": self.root,
            "checks": [
                {"name": o.name, "command": o.command, "status": o.status,
                 "exit_code": o.exit_code, "duration_ms": o.duration_ms,
                 **({"output": o.output} if o.output else {})}
                for o in self.outcomes
            ],
            **({"note": self.note} if self.note else {}),
            **({"hint": _hint(failed)} if failed else {}),
        }


def _hint(failed: CheckOutcome) -> str:
    base = (f"`{failed.command}` failed. Read the output above, fix the ROOT CAUSE "
            "in the source, and call workspace_check again. Do not weaken, skip "
            "or delete a test or a type to make it pass.")
    if failed.name == "install":
        return ("Dependency installation failed, so nothing else was run. Check the "
                "package names and versions in the manifest. " + base)
    return base


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def find_project_root(workspace: Path, subdir: str = "") -> Path:
    """The directory holding the manifest.

    Models scaffold into a subfolder (`npm create vite@latest todo`) as often as
    into the root, so a root with no manifest and exactly one child that has
    one is resolved to that child.
    """
    base = (workspace / subdir) if subdir else workspace
    markers = ("package.json", "pyproject.toml", "setup.py", "requirements.txt",
               "Cargo.toml", "go.mod")
    if any((base / m).exists() for m in markers):
        return base
    children = [c for c in sorted(base.iterdir()) if c.is_dir()
                and not c.name.startswith(".") and c.name != "node_modules"] if base.is_dir() else []
    candidates = [c for c in children if any((c / m).exists() for m in markers)]
    return candidates[0] if len(candidates) == 1 else base


def detect(root: Path, *,
           has_tool: Callable[[str], bool] = lambda _name: True) -> tuple[list[Check], str]:
    """The checks this project declares, in the order they should run."""
    checks: list[Check] = []
    notes: list[str] = []

    package = root / "package.json"
    if package.exists():
        manifest = _read_json(package)
        scripts = manifest.get("scripts") or {}
        deps = {**(manifest.get("dependencies") or {}), **(manifest.get("devDependencies") or {})}
        if deps and not (root / "node_modules").exists():
            lock = (root / "package-lock.json").exists()
            checks.append(Check("install", "npm ci" if lock else "npm install", timeout=900))
        used: set[str] = set()
        for name, candidates in _SCRIPT_ORDER:
            script = next((s for s in candidates if s in scripts and s not in used), None)
            if not script:
                continue
            body = str(scripts[script])
            if _LONG_RUNNING.search(script) or (name == "test" and _WATCH_FLAGS.search(body)):
                notes.append(f"skipped `{script}`: it starts a watcher")
                continue
            if name == "test" and re.search(r"no test specified", body, re.I):
                continue
            used.add(script)
            checks.append(Check(name, f"npm run {script}", timeout=900 if name == "build" else 600))
        if "typecheck" not in {c.name for c in checks} and (root / "tsconfig.json").exists() \
                and "typescript" in deps:
            checks.insert(1 if checks and checks[0].name == "install" else 0,
                          Check("typecheck", "npx tsc --noEmit"))

    python_markers = [root / m for m in ("pyproject.toml", "setup.py", "requirements.txt")]
    if any(m.exists() for m in python_markers):
        tests = any((root / d).is_dir() for d in ("tests", "test")) or any(root.glob("test_*.py"))
        if tests:
            checks.append(Check("test", "python -m pytest -q", timeout=900))
        else:
            checks.append(Check("compile", "python -m compileall -q .", timeout=300))

    if (root / "Cargo.toml").exists() and has_tool("cargo"):
        checks.append(Check("test", "cargo test --quiet", timeout=1200))
    if (root / "go.mod").exists() and has_tool("go"):
        checks += [Check("vet", "go vet ./..."), Check("test", "go test ./...", timeout=900)]

    if not checks:
        if any(root.glob("*.html")):
            notes.append("static site: open it with workspace_serve + preview_check, "
                         "or verify_artifact with workspace_path")
        else:
            notes.append("no manifest with checks was found")
    return checks, "; ".join(notes)


def run(root: Path, checks: list[Check], execute: Callable[[str, int], object],
        rel_root: str) -> CheckReport:
    """Run checks fail-fast. `execute(command, timeout)` returns an ExecResult."""
    report = CheckReport(root=rel_root or ".", detected=[c.name for c in checks])
    prefix = f"cd {json.dumps(rel_root)} && " if rel_root not in {"", "."} else ""
    for check in checks:
        res = execute(prefix + check.command, check.timeout)
        output = ((getattr(res, "stdout", "") or "") + "\n" + (getattr(res, "stderr", "") or "")).strip()
        tail = output[-3500:]
        status = getattr(res, "status", "error")
        code = int(getattr(res, "exit_code", 1) or 0)
        if status == "timeout":
            outcome = CheckOutcome(check.name, check.command, "timeout", 124,
                                   getattr(res, "duration_ms", 0), tail)
        elif status == "ok" and code == 0:
            outcome = CheckOutcome(check.name, check.command, "passed", 0,
                                   getattr(res, "duration_ms", 0))
        elif _UNAVAILABLE.search(output):
            outcome = CheckOutcome(check.name, check.command, "skipped", code,
                                   getattr(res, "duration_ms", 0),
                                   "this tool is not available here: " + tail[-400:])
        else:
            outcome = CheckOutcome(check.name, check.command, "failed", code or 1,
                                   getattr(res, "duration_ms", 0), tail)
        report.outcomes.append(outcome)
        if outcome.status in {"failed", "timeout"}:
            break
    return report
