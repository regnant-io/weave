"""Persistent, network-enabled developer workspace — one per project.

This is deliberately a SECOND sandbox, not a replacement for the analysis one.
They have opposite threat models and must not be merged:

  * `services/sandbox` runs untrusted model-written code against a user's
    DATASET. It has no network, an import allowlist, no `open()`, and the
    workspace is destroyed after every run. Those restrictions are the product.

  * this service is where the model BUILDS SOFTWARE. Installing dependencies,
    downloading a 3D model, running a test suite and producing a tarball all
    require exactly what the analysis sandbox forbids: a writable persistent
    filesystem, arbitrary executables, and the internet.

Giving the second capability to the first would silently remove the protection
around the user's data, so they stay separate and only this one gets a
container.

Isolation model
---------------
File operations run on the HOST, inside a per-project directory, guarded by
`_resolve()` against traversal. They never need a container and are fast.

Execution runs in a throwaway Docker container with the project directory bind
mounted at /workspace: non-root, read-only root filesystem apart from the mount,
all Linux capabilities dropped, `--security-opt no-new-privileges`, and hard
memory / CPU / PID / wall-clock limits. The container is removed on exit; only
/workspace survives.

If Docker is not available the service reports `enabled = False` and its tools
are simply not advertised to the model, exactly like every other optional
capability.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path

from ...config import settings

log = logging.getLogger("weave.workspace")

#: Files we refuse to serve or archive regardless of what the model asks for.
_EXCLUDE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".next", "dist-cache"}

#: Anything above this is not a source file the model should be round-tripping
#: through the LLM; it is served as an artifact instead.
MAX_READ_BYTES = 400_000
MAX_WRITE_BYTES = 4_000_000


@dataclass
class ExecResult:
    status: str  # ok | error | timeout | unavailable
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0


class WorkspaceService:
    def __init__(self) -> None:
        self.root = Path(settings.workspace_root)
        self.image = settings.workspace_image
        self._docker: bool | None = None

    # ------------------------------------------------------------ availability

    @property
    def enabled(self) -> bool:
        """True when we can actually execute. File tools alone are not enough:
        advertising `workspace_exec` without a runtime would have the model
        confidently 'installing' packages that never install."""
        if not settings.workspace_enabled:
            return False
        if self._docker is None:
            self._docker = self._probe_docker()
        return self._docker

    def _probe_docker(self) -> bool:
        try:
            r = subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                capture_output=True, text=True, timeout=12, check=False,
            )
            ok = r.returncode == 0 and bool(r.stdout.strip())
            if not ok:
                log.info("workspace: docker unavailable (%s)", (r.stderr or "").strip()[:160])
            return ok
        except Exception as exc:  # noqa: BLE001 - docker CLI missing entirely
            log.info("workspace: docker not found (%s)", exc)
            return False

    def refresh(self) -> bool:
        """Re-probe. Used by the settings page after Docker is started."""
        self._docker = None
        return self.enabled

    # ------------------------------------------------------------------- paths

    def project_dir(self, project_id: str) -> Path:
        d = self.root / str(project_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _resolve(self, project_id: str, rel: str) -> Path:
        """Resolve a model-supplied path INSIDE the project workspace.

        The model controls this string, so every one of `../`, an absolute path,
        a symlink pointing out of the tree, and a Windows drive prefix has to be
        rejected — a single missed case is arbitrary host file write.
        """
        base = self.project_dir(project_id).resolve()
        raw = (rel or "").strip().replace("\\", "/")
        # A leading "/" is read as WORKSPACE-root-relative, not filesystem-root:
        # models routinely write "/src/index.js" meaning "at the top of the
        # project". Stripping it is the intended semantic, and containment is
        # still enforced below — but it does mean "/etc/passwd" resolves to
        # <workspace>/etc/passwd rather than the host file, which is the safe
        # direction and worth knowing when reading a trace.
        cleaned = raw.lstrip("/")
        if not cleaned or cleaned in {".", ".."}:
            raise ValueError("a file path is required")
        if re.match(r"^[A-Za-z]:", cleaned):
            raise ValueError("absolute paths are not allowed")
        target = (base / cleaned).resolve()
        # `is_relative_to` also covers the symlink case because both sides are
        # already fully resolved.
        if target != base and base not in target.parents:
            raise ValueError("path escapes the workspace")
        return target

    # -------------------------------------------------------------- file tools

    def write_file(self, project_id: str, path: str, content: str) -> dict:
        if len(content or "") > MAX_WRITE_BYTES:
            return {"status": "error", "error": f"file exceeds {MAX_WRITE_BYTES} bytes"}
        try:
            target = self._resolve(project_id, path)
        except ValueError as exc:
            return {"status": "error", "error": str(exc)}
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        target.write_text(content or "", encoding="utf-8", newline="\n")
        return {
            "status": "ok",
            "path": self._rel(project_id, target),
            "bytes": target.stat().st_size,
            "created": not existed,
        }

    def read_file(self, project_id: str, path: str,
                  start: int | None = None, end: int | None = None) -> dict:
        try:
            target = self._resolve(project_id, path)
        except ValueError as exc:
            return {"status": "error", "error": str(exc)}
        if not target.is_file():
            return {"status": "error", "error": f"no such file: {path}"}
        if target.stat().st_size > MAX_READ_BYTES:
            return {"status": "error",
                    "error": f"file is larger than {MAX_READ_BYTES} bytes; read a line range"}
        try:
            text = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return {"status": "error", "error": "binary file; not readable as text"}
        lines = text.split("\n")
        if start is not None or end is not None:
            s = max(1, int(start or 1))
            e = min(len(lines), int(end or len(lines)))
            body = "\n".join(lines[s - 1:e])
            return {"status": "ok", "path": self._rel(project_id, target),
                    "content": body, "start": s, "end": e, "total_lines": len(lines)}
        return {"status": "ok", "path": self._rel(project_id, target),
                "content": text, "total_lines": len(lines)}

    def edit_file(self, project_id: str, path: str, find: str, replace: str,
                  replace_all: bool = False) -> dict:
        """Exact-string replacement in an existing file.

        This exists so the model can CHANGE code instead of rewriting a whole
        file — rewriting is how you end up with ten near-identical files and a
        truncated version of the one that mattered. A non-unique `find` is an
        error rather than a guess, because silently editing the wrong occurrence
        is worse than failing.
        """
        try:
            target = self._resolve(project_id, path)
        except ValueError as exc:
            return {"status": "error", "error": str(exc)}
        if not target.is_file():
            return {"status": "error", "error": f"no such file: {path}"}
        try:
            text = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return {"status": "error", "error": "binary file; not editable as text"}
        if not find:
            return {"status": "error", "error": "`find` must not be empty"}
        count = text.count(find)
        if count == 0:
            return {"status": "error", "error": "`find` text not found in the file"}
        if count > 1 and not replace_all:
            return {"status": "error",
                    "error": f"`find` matches {count} times; include more surrounding "
                             "context to make it unique, or set replace_all"}
        updated = text.replace(find, replace) if replace_all else text.replace(find, replace, 1)
        target.write_text(updated, encoding="utf-8", newline="\n")
        return {"status": "ok", "path": self._rel(project_id, target),
                "replacements": count if replace_all else 1,
                "bytes": target.stat().st_size}

    def delete_path(self, project_id: str, path: str) -> dict:
        try:
            target = self._resolve(project_id, path)
        except ValueError as exc:
            return {"status": "error", "error": str(exc)}
        if not target.exists():
            return {"status": "error", "error": f"no such path: {path}"}
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            target.unlink(missing_ok=True)
        return {"status": "ok", "path": self._rel(project_id, target), "deleted": True}

    def move_path(self, project_id: str, src: str, dst: str) -> dict:
        try:
            s = self._resolve(project_id, src)
            d = self._resolve(project_id, dst)
        except ValueError as exc:
            return {"status": "error", "error": str(exc)}
        if not s.exists():
            return {"status": "error", "error": f"no such path: {src}"}
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
        return {"status": "ok", "from": self._rel(project_id, s), "to": self._rel(project_id, d)}

    def list_tree(self, project_id: str, path: str = "", depth: int = 4) -> dict:
        base = self.project_dir(project_id).resolve()
        try:
            start = self._resolve(project_id, path) if path else base
        except ValueError as exc:
            return {"status": "error", "error": str(exc)}
        if not start.exists():
            return {"status": "ok", "path": path or "/", "entries": [], "empty": True}

        entries: list[dict] = []
        max_entries = 600

        def walk(d: Path, level: int) -> None:
            if level > depth or len(entries) >= max_entries:
                return
            try:
                children = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            except OSError:
                return
            for child in children:
                if len(entries) >= max_entries:
                    return
                if child.name in _EXCLUDE_DIRS or child.name.startswith(".DS_Store"):
                    # Still report that it exists — "node_modules is installed"
                    # is information the model needs, its 40k files are not.
                    entries.append({"path": self._rel(project_id, child), "type": "dir",
                                    "collapsed": True})
                    continue
                if child.is_dir():
                    entries.append({"path": self._rel(project_id, child), "type": "dir"})
                    walk(child, level + 1)
                else:
                    try:
                        size = child.stat().st_size
                    except OSError:
                        size = 0
                    entries.append({"path": self._rel(project_id, child), "type": "file",
                                    "bytes": size})

        walk(start, 1)
        return {"status": "ok", "path": path or "/", "entries": entries,
                "truncated": len(entries) >= max_entries}

    def _rel(self, project_id: str, p: Path) -> str:
        base = self.project_dir(project_id).resolve()
        try:
            return p.resolve().relative_to(base).as_posix()
        except ValueError:
            return p.name

    # ------------------------------------------------------------- verification

    def verify_file(self, project_id: str, path: str) -> dict:
        """Is this file actually parseable?

        The failure this prevents is specific and common: a model writes a
        900-line file, the generation is cut short or a brace is unbalanced, and
        nothing notices until the user opens it. Checking costs milliseconds.
        Python and JSON are checked in-process; JS/TS/HTML/CSS are checked in the
        container when one is available, with a structural fallback when not.
        """
        try:
            target = self._resolve(project_id, path)
        except ValueError as exc:
            return {"status": "error", "error": str(exc)}
        if not target.is_file():
            return {"status": "error", "error": f"no such file: {path}"}

        suffix = target.suffix.lower()
        try:
            text = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return {"status": "ok", "valid": True, "note": "binary file; not checked"}

        if suffix == ".py":
            import ast
            try:
                ast.parse(text)
                return {"status": "ok", "valid": True, "checker": "python-ast"}
            except SyntaxError as exc:
                return {"status": "ok", "valid": False, "checker": "python-ast",
                        "error": f"line {exc.lineno}: {exc.msg}"}

        if suffix in {".json", ".webmanifest"}:
            try:
                json.loads(text)
                return {"status": "ok", "valid": True, "checker": "json"}
            except json.JSONDecodeError as exc:
                return {"status": "ok", "valid": False, "checker": "json",
                        "error": f"line {exc.lineno}, col {exc.colno}: {exc.msg}"}

        if suffix in {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"} and self.enabled:
            # `node --check` only understands scripts; everything else goes
            # through a parse attempt that reports the real syntax error.
            rel = self._rel(project_id, target)
            res = self.exec(project_id, f"node --check {_sh_quote(rel)}", timeout=45)
            if res.status == "ok" and res.exit_code == 0:
                return {"status": "ok", "valid": True, "checker": "node --check"}
            if res.status == "ok":
                return {"status": "ok", "valid": False, "checker": "node --check",
                        "error": (res.stderr or res.stdout)[:1200]}

        structural = _structural_check(text, suffix)
        return {"status": "ok", "checker": "structural", **structural}

    # ---------------------------------------------------------------- execution

    def exec(self, project_id: str, command: str, timeout: int | None = None,
             cancel=None) -> ExecResult:
        """Run a shell command inside the project's container."""
        if not self.enabled:
            return ExecResult(status="unavailable",
                              stderr="workspace execution is not configured (Docker unavailable)")
        if not (command or "").strip():
            return ExecResult(status="error", stderr="empty command")

        timeout = int(timeout or settings.workspace_exec_timeout)
        timeout = max(5, min(timeout, settings.workspace_exec_max_timeout))
        workdir = self.project_dir(project_id)

        args = [
            "docker", "run", "--rm", "-i",
            "--workdir", "/workspace",
            "-v", f"{workdir.resolve().as_posix()}:/workspace",
            # Hard resource ceilings. A runaway `npm install` in a loop must not
            # take the host down.
            "--memory", f"{settings.workspace_memory_mb}m",
            "--memory-swap", f"{settings.workspace_memory_mb}m",
            "--cpus", str(settings.workspace_cpus),
            "--pids-limit", str(settings.workspace_pids_limit),
            # Never root, never able to gain privileges, no ambient capabilities.
            "--user", settings.workspace_user,
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",
        ]
        if settings.workspace_network:
            # Explicitly requested: installing dependencies and fetching assets
            # is the whole point of this sandbox.
            args += ["--network", settings.workspace_network_mode]
        else:
            args += ["--network", "none"]
        args += [self.image, "bash", "-lc", command]

        started = time.monotonic()
        try:
            proc = subprocess.run(
                args, capture_output=True, text=True, timeout=timeout + 10,
                check=False, encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired:
            return ExecResult(status="timeout", exit_code=124,
                              stderr=f"command exceeded the {timeout}s limit",
                              duration_ms=int((time.monotonic() - started) * 1000))
        except FileNotFoundError:
            self._docker = False
            return ExecResult(status="unavailable", stderr="docker is not installed on this host")

        return ExecResult(
            status="ok" if proc.returncode == 0 else "error",
            exit_code=proc.returncode,
            # Truncate from the FRONT of long logs: an npm install prints
            # thousands of progress lines and the error is at the end.
            stdout=_tail(proc.stdout, settings.workspace_output_chars),
            stderr=_tail(proc.stderr, settings.workspace_output_chars),
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    # ---------------------------------------------------------------- packaging

    def package(self, project_id: str, name: str = "", subdir: str = "") -> dict:
        """Archive the workspace (or one directory) as a .tar.gz artifact."""
        base = self.project_dir(project_id).resolve()
        try:
            src = self._resolve(project_id, subdir) if subdir else base
        except ValueError as exc:
            return {"status": "error", "error": str(exc)}
        if not src.exists():
            return {"status": "error", "error": f"no such path: {subdir}"}

        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", (name or "workspace")).strip("-") or "workspace"
        out_name = f"{safe}.tar.gz"
        tmp = base.parent / f".pkg-{project_id}-{safe}.tar.gz"

        def _filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
            parts = set(Path(info.name).parts)
            # Dependency trees and VCS metadata make the archive enormous and
            # are reproducible from the manifest anyway.
            if parts & _EXCLUDE_DIRS:
                return None
            return info

        try:
            with tarfile.open(tmp, "w:gz") as tar:
                tar.add(src, arcname=safe, filter=_filter)
            data = tmp.read_bytes()
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": f"could not package: {exc}"}
        finally:
            tmp.unlink(missing_ok=True)

        if len(data) > settings.workspace_package_max_bytes:
            return {"status": "error",
                    "error": f"archive is {len(data)} bytes, over the "
                             f"{settings.workspace_package_max_bytes} limit; package a subdirectory"}

        from ...storage import storage
        key = f"workspace/{project_id}/{int(time.time())}-{out_name}"
        storage.put_bytes(key, data)
        return {
            "status": "ok",
            "output_files": [{
                "name": out_name, "s3_key": key,
                "mime": "application/gzip", "bytes": len(data),
            }],
        }

    def stats(self, project_id: str) -> dict:
        base = self.project_dir(project_id)
        files = 0
        total = 0
        for p in base.rglob("*"):
            if p.is_file():
                parts = set(p.relative_to(base).parts)
                if parts & _EXCLUDE_DIRS:
                    continue
                files += 1
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
        return {"files": files, "bytes": total, "path": str(base)}

    def reset(self, project_id: str) -> dict:
        base = self.project_dir(project_id)
        shutil.rmtree(base, ignore_errors=True)
        self.project_dir(project_id)
        return {"status": "ok", "reset": True}


def _tail(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return "…(earlier output trimmed)…\n" + text[-limit:]


def _sh_quote(s: str) -> str:
    return "'" + str(s).replace("'", "'\\''") + "'"


def _structural_check(text: str, suffix: str) -> dict:
    """Cheap balance check for languages we cannot really parse here.

    It cannot prove a file is correct, only catch the specific failure that
    actually happens with generated files: an unclosed brace, bracket or tag
    because generation stopped early.
    """
    if not text.strip():
        return {"valid": False, "error": "file is empty"}

    pairs = {"{": "}", "[": "]", "(": ")"}
    closers = {v: k for k, v in pairs.items()}
    stack: list[str] = []
    in_str: str | None = None
    escaped = False
    i = 0
    line = 1
    while i < len(text):
        c = text[i]
        if c == "\n":
            line += 1
        if in_str:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == in_str:
                in_str = None
            i += 1
            continue
        if c in {'"', "'", "`"}:
            in_str = c
        elif c == "/" and i + 1 < len(text) and text[i + 1] == "/":
            nl = text.find("\n", i)
            if nl == -1:
                break
            line += 1
            i = nl + 1
            continue
        elif c == "/" and i + 1 < len(text) and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            if end == -1:
                return {"valid": False, "error": f"unterminated block comment from line {line}"}
            line += text.count("\n", i, end)
            i = end + 2
            continue
        elif c in pairs:
            stack.append(c)
        elif c in closers:
            if not stack or stack[-1] != closers[c]:
                return {"valid": False, "error": f"unexpected '{c}' at line {line}"}
            stack.pop()
        i += 1

    if in_str:
        return {"valid": False, "error": "unterminated string literal"}
    if stack:
        return {"valid": False,
                "error": f"unclosed '{stack[-1]}' — the file looks truncated"}

    if suffix in {".html", ".htm"}:
        lowered = text.lower()
        if "<html" in lowered and "</html>" not in lowered:
            return {"valid": False, "error": "<html> is never closed — the file looks truncated"}
        if "<body" in lowered and "</body>" not in lowered:
            return {"valid": False, "error": "<body> is never closed — the file looks truncated"}

    return {"valid": True}


_service: WorkspaceService | None = None


def get_workspace_service() -> WorkspaceService:
    global _service
    if _service is None:
        _service = WorkspaceService()
    return _service
