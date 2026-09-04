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

Execution runs in ONE LONG-LIVED Docker container per project, with the project
directory bind-mounted at /workspace: non-root, all Linux capabilities dropped,
`--security-opt no-new-privileges`, and hard memory / CPU / PID / wall-clock
limits. Commands run through `docker exec`.

It used to be a throwaway container per command, which is a tidier model and
made three things impossible: a dev server (a process that never returns always
hit the timeout, so a web app could be built and never once looked at), any warm
state between commands, and a fast build-test-fix loop (a second of container
creation per command, thirty times over). The security posture is unchanged —
those properties belong to how the container is created, and it is still created
that way. Only its lifetime changed. Idle containers are reaped by label.

Dev servers get their ports published to the host loopback for the user's
browser, and are reachable by container name on the Docker network so
Browserless can open and screenshot the running app — which is what lets the
assistant check its own web app instead of asking the user to look.

If Docker is not available the service reports `enabled = False` and its tools
are simply not advertised to the model, exactly like every other optional
capability.
"""
from __future__ import annotations

import fnmatch
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
        self._net: str | None = None
        #: container name -> monotonic timestamp of its last command. Drives
        #: idle reaping; empty after a restart, which reap_idle handles by
        #: giving an unknown container one grace period.
        self._last_used: dict[str, float] = {}

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
        # Checked every time rather than only on creation: a directory made
        # before ownership was handled stays root-owned forever otherwise, and
        # the symptom (every command fails with EACCES, every file write
        # succeeds) is the same confusing one this is meant to prevent. A stat
        # is far cheaper than that bug.
        self._own(d, only_if_foreign=True)
        return d

    def _own(self, path: Path, only_if_foreign: bool = False) -> None:
        """Hand a path to the uid the workspace container runs as.

        The backend runs as root and creates these directories; the container
        runs as uid 1000 and has to write into them. Without this every command
        the model runs fails with EACCES while `workspace_write` keeps working
        (it writes host-side, as root) — which presents as a model that cannot
        install a package but can create files, and is very hard to read.

        Silently best-effort: on a synthesised filesystem chown is a no-op and
        raising here would take down file writing over a permissions model that
        does not exist on that host.
        """
        try:
            uid, _, gid = str(settings.workspace_user or "1000:1000").partition(":")
            uid, gid = int(uid), int(gid or uid)
            if only_if_foreign and path.stat().st_uid == uid:
                return
            os.chown(path, uid, gid)
        except Exception:  # noqa: BLE001 - no chown on this filesystem, or not root
            pass

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

    #: Directories that are never worth searching and are frequently enormous.
    #: Walking node_modules once can be more files than the rest of the project
    #: put together, and nothing in it is the model's own code.
    _SEARCH_SKIP = {
        "node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build",
        ".next", ".cache", "target", ".pytest_cache", ".mypy_cache",
    }
    _TEXT_SUFFIXES = {
        ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".md", ".txt", ".csv", ".tsv",
        ".html", ".css", ".scss", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".sh",
        ".sql", ".r", ".R", ".java", ".c", ".h", ".cpp", ".go", ".rs", ".rb", ".php",
        ".xml", ".svg", ".env", ".gitignore", ".dockerignore", "",
    }

    def _walk_files(self, base: Path):
        """Every file under `base`, skipping dependency and build directories."""
        stack = [base]
        while stack:
            current = stack.pop()
            try:
                entries = list(current.iterdir())
            except OSError:
                continue
            for entry in entries:
                if entry.is_symlink():
                    continue  # never follow a link out of the tree
                if entry.is_dir():
                    if entry.name not in self._SEARCH_SKIP:
                        stack.append(entry)
                elif entry.is_file():
                    yield entry

    def glob_files(self, project_id: str, pattern: str = "**/*", limit: int = 200) -> dict:
        """Find files by glob. Returns paths only — reading them is a separate step.

        Locating a file is a different question from reading it, and answering
        the first with the contents of forty files is how a context window
        disappears before any work starts.
        """
        base = self.project_dir(project_id).resolve()
        pattern = (pattern or "**/*").strip().lstrip("/")
        out: list[dict] = []
        truncated = False
        try:
            for path in base.glob(pattern):
                if not path.is_file() or path.is_symlink():
                    continue
                if any(part in self._SEARCH_SKIP for part in path.parts):
                    continue
                if len(out) >= limit:
                    truncated = True
                    break
                try:
                    stat = path.stat()
                except OSError:
                    continue
                out.append({"path": self._rel(project_id, path), "bytes": stat.st_size})
        except (ValueError, OSError) as exc:
            return {"status": "error", "error": f"bad pattern: {exc}"}
        out.sort(key=lambda f: f["path"])
        return {"status": "ok", "pattern": pattern, "count": len(out),
                "truncated": truncated, "files": out}

    def grep(self, project_id: str, pattern: str, *, glob: str = "",
             case_sensitive: bool = False, max_matches: int = 120,
             context: int = 0) -> dict:
        """Regex search across the workspace, returning matching LINES.

        Implemented in Python rather than by shelling out to grep because this
        must work identically whether or not the exec container is available —
        searching is how the model orients itself in an existing project, and it
        should not stop working when Docker does.
        """
        if not (pattern or "").strip():
            return {"status": "error", "error": "a search pattern is required"}
        try:
            regex = re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
        except re.error as exc:
            return {"status": "error", "error": f"invalid regular expression: {exc}"}

        base = self.project_dir(project_id).resolve()
        want = (glob or "").strip()
        matches: list[dict] = []
        files_searched = 0
        truncated = False

        for path in self._walk_files(base):
            if path.suffix.lower() not in self._TEXT_SUFFIXES:
                continue
            rel = self._rel(project_id, path)
            if want and not fnmatch.fnmatch(rel, want) and not fnmatch.fnmatch(path.name, want):
                continue
            try:
                if path.stat().st_size > 2_000_000:
                    continue  # a 2MB single file is data, not source
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            files_searched += 1
            for i, line in enumerate(lines):
                if not regex.search(line):
                    continue
                if len(matches) >= max_matches:
                    truncated = True
                    break
                entry = {"path": rel, "line": i + 1, "text": line.rstrip()[:400]}
                if context > 0:
                    lo, hi = max(0, i - context), min(len(lines), i + context + 1)
                    entry["context"] = [ln.rstrip()[:400] for ln in lines[lo:hi]]
                matches.append(entry)
            if truncated:
                break

        return {
            "status": "ok", "pattern": pattern, "files_searched": files_searched,
            "count": len(matches), "truncated": truncated, "matches": matches,
        }

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

    # ------------------------------------------------------- the live container
    #
    # Execution used to be one `docker run --rm` per command. That is a clean
    # model and it made three things impossible:
    #
    #   * A DEV SERVER. `npm run dev` never returns, so it always hit the
    #     timeout and was killed. The model could build a web app and could
    #     never once look at it running — which is most of the distance between
    #     this and a real development environment.
    #   * WARM STATE. Every command started a fresh container, so nothing
    #     survived but the bind mount. Fine for files, useless for a running
    #     process, a background build, or an installed global.
    #   * SPEED. Container creation is ~1s. On a build-test-fix loop of thirty
    #     commands that is half a minute of pure overhead.
    #
    # So each project gets ONE long-lived container and commands run with
    # `docker exec`. The security posture is unchanged — non-root, all
    # capabilities dropped, no-new-privileges, hard memory/CPU/PID ceilings —
    # because those are properties of how the container was created, and it is
    # still created that way. What changes is only its lifetime.

    #: Ports published from every workspace container, covering the defaults of
    #: the dev servers that actually get used (Vite, Next/CRA, Python http.server
    #: and friends). Published on 127.0.0.1 with an ephemeral host port, so
    #: nothing is exposed off-box and two projects never collide.
    DEV_PORTS = (5173, 3000, 8000, 8080)

    def container_name(self, project_id: str) -> str:
        return f"weave-ws-{_safe_id(project_id)}"

    def host_path(self, project_id: str) -> str:
        """The project directory AS THE DOCKER DAEMON SEES IT.

        This is the bug that made the whole workspace a no-op, and it is worth
        being precise about because it looked like it worked.

        `docker run -v SRC:/workspace` is interpreted by the DAEMON, on the
        host. The backend was passing its own in-container path
        (`/app/var/workspaces/<id>`), which on the host names nothing — so
        Docker helpfully created a brand-new empty directory there and mounted
        that. Every command therefore ran against an empty /workspace, could not
        see a single file the model had written, and could not write anything
        back that the model would ever read. Files were written host-side and
        read host-side, so `workspace_write` then `workspace_read` round-tripped
        perfectly and the failure only appeared when a COMMAND was involved:
        `npm install` in an empty directory, a test run that found no tests, a
        build with no source. Which reads as the model being confused.

        So: ask Docker where our own mount actually comes from, and translate.
        Self-configuring, because a configured host path is a setting that is
        wrong on every machine but the one it was written on.
        """
        local = self.project_dir(project_id).resolve()
        base = self._host_root()
        if not base:
            return local.as_posix()
        rel = local.relative_to(Path(settings.workspace_root).resolve())
        # Host separator, not ours: the daemon may be on Windows while this
        # process is in a Linux container.
        sep = "\\" if ("\\" in base and ":" in base[:3]) else "/"
        return base.rstrip("/\\") + sep + str(rel).replace("/", sep).replace("\\", sep)

    def _root_mount(self) -> dict:
        """How `workspace_root` is backed, as Docker sees it.

        Returns {"type": "volume"|"bind"|"", "name": ..., "source": ..., "sub": ...}
        where `sub` is the path from the mount point down to the workspace root.

        Two shapes are supported, and which one you get decides whether the
        container can write:

          * VOLUME (what compose now provides). Real ext4 inside the VM, so
            ownership is real and each project is mounted with
            `volume-subpath`. The container stays non-root.
          * BIND. Used when someone has bind-mounted a host directory. On Linux
            this works if the directory is owned by the workspace uid; on Docker
            Desktop the host filesystem synthesises ownership, chown is a no-op,
            and the container cannot write — see `_mount_args`.
        """
        cached = getattr(self, "_rmount", None)
        if cached is not None:
            return cached
        out = {"type": "", "name": "", "source": "", "sub": ""}
        try:
            import json as _json
            import socket

            r = subprocess.run(
                ["docker", "inspect", socket.gethostname(), "--format", "{{json .Mounts}}"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            if r.returncode == 0:
                root = Path(settings.workspace_root).resolve()
                best = -1
                for m in _json.loads(r.stdout or "[]"):
                    dest_raw = str(m.get("Destination") or "")
                    if not dest_raw:
                        continue
                    dest = Path(dest_raw)
                    if root != dest and dest not in root.parents:
                        continue
                    depth = len(dest.parts)
                    if depth <= best:
                        continue
                    best = depth
                    out = {
                        "type": str(m.get("Type") or ""),
                        "name": str(m.get("Name") or ""),
                        "source": str(m.get("Source") or ""),
                        "sub": "" if root == dest else root.relative_to(dest).as_posix(),
                    }
        except Exception as exc:  # noqa: BLE001 - not containerised: paths are host paths
            log.debug("workspace: could not resolve root mount (%s)", exc)
        self._rmount = out
        log.info("workspace: root is backed by %s", out or "the local filesystem")
        return out

    def _host_root(self) -> str:
        """Host path backing `workspace_root` (bind case only)."""
        mount = self._root_mount()
        if mount.get("type") != "bind" or not mount.get("source"):
            return ""
        src, sub = mount["source"], mount.get("sub") or ""
        if not sub:
            return src
        sep = "\\" if ("\\" in src and ":" in src[:3]) else "/"
        return src.rstrip("/\\") + sep + sub.replace("/", sep)

    def _mount_args(self, project_id: str) -> list[str]:
        """How to give the container this project's directory."""
        mount = self._root_mount()
        sub = (mount.get("sub") or "").strip("/")
        pid = _safe_id(project_id)

        if mount.get("type") == "volume" and mount.get("name"):
            inner = f"{sub}/{pid}" if sub else pid
            return ["--mount",
                    f"type=volume,source={mount['name']},target=/workspace,"
                    f"volume-subpath={inner}"]

        # Bind, or not containerised at all.
        return ["-v", f"{self.host_path(project_id)}:/workspace"]

    def _network(self) -> str:
        """The Docker network to attach workspace containers to.

        Discovered from the backend's OWN container rather than configured,
        because the two have to match for anything to work: Browserless has to
        be able to reach a dev server by container name to screenshot it. A
        hard-coded network name is a setting that is wrong on every deployment
        whose compose project is not called "weave".
        """
        if getattr(self, "_net", None) is not None:
            return self._net
        net = settings.workspace_network_mode or "bridge"
        try:
            import socket

            r = subprocess.run(
                ["docker", "inspect", socket.gethostname(), "--format",
                 "{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            found = (r.stdout or "").strip().splitlines()
            if r.returncode == 0 and found and found[0].strip():
                net = found[0].strip()
        except Exception as exc:  # noqa: BLE001 - not in a container, or no socket
            log.debug("workspace: could not detect network (%s); using %s", exc, net)
        self._net = net
        return net

    def _container_state(self, name: str) -> str:
        """'running', 'exited', 'missing' — whatever Docker actually thinks."""
        try:
            r = subprocess.run(
                ["docker", "inspect", name, "--format", "{{.State.Status}}"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            if r.returncode != 0:
                return "missing"
            return (r.stdout or "").strip() or "missing"
        except Exception:  # noqa: BLE001
            return "missing"

    def ensure_container(self, project_id: str) -> ExecResult:
        """Start this project's container if it is not already up."""
        name = self.container_name(project_id)
        state = self._container_state(name)
        if state == "running":
            return ExecResult(status="ok")
        if state != "missing":
            # Exited or created: a restart preserves the published port mapping,
            # which a remove-and-recreate would change under any preview URL the
            # user already has open.
            r = subprocess.run(["docker", "start", name], capture_output=True,
                               text=True, timeout=60, check=False)
            if r.returncode == 0:
                return ExecResult(status="ok")
            subprocess.run(["docker", "rm", "-f", name], capture_output=True,
                           text=True, timeout=60, check=False)

        self.project_dir(project_id)          # make sure it exists before mounting
        args = [
            "docker", "run", "-d", "--name", name,
            "--workdir", "/workspace",
        ]
        # Volume subpath, or a host-path bind — see `_mount_args`.
        args += self._mount_args(project_id)
        args += [
            "--memory", f"{settings.workspace_memory_mb}m",
            "--memory-swap", f"{settings.workspace_memory_mb}m",
            "--cpus", str(settings.workspace_cpus),
            "--pids-limit", str(settings.workspace_pids_limit),
            "--user", settings.workspace_user,
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",
            # Labelled so the reaper can find every workspace container without
            # keeping its own registry, which would go stale across a restart.
            "--label", "weave.workspace=1",
            "--label", f"weave.project={_safe_id(project_id)}",
        ]
        if settings.workspace_network:
            args += ["--network", self._network()]
            for port in self.DEV_PORTS:
                args += ["-p", f"127.0.0.1::{port}"]
        else:
            args += ["--network", "none"]
        # `sleep infinity` as PID 1: the container exists to be exec'd into, and
        # anything longer-lived would be a second thing to reason about.
        args += ["--entrypoint", "sleep", self.image, "infinity"]

        r = subprocess.run(args, capture_output=True, text=True, timeout=120, check=False)
        if r.returncode != 0:
            err = (r.stderr or "").strip()
            log.warning("workspace: could not start container %s: %s", name, err[:300])
            return ExecResult(status="error", stderr=err[:600] or "could not start the workspace")
        return ExecResult(status="ok")

    def ports(self, project_id: str) -> dict[int, int]:
        """container port -> host port, for whatever is published."""
        name = self.container_name(project_id)
        out: dict[int, int] = {}
        for port in self.DEV_PORTS:
            try:
                r = subprocess.run(["docker", "port", name, f"{port}/tcp"],
                                   capture_output=True, text=True, timeout=10, check=False)
                line = (r.stdout or "").strip().splitlines()
                if r.returncode == 0 and line:
                    out[port] = int(line[0].rsplit(":", 1)[1])
            except Exception:  # noqa: BLE001
                continue
        return out

    def stop_container(self, project_id: str) -> dict:
        name = self.container_name(project_id)
        subprocess.run(["docker", "rm", "-f", name], capture_output=True,
                       text=True, timeout=60, check=False)
        return {"status": "ok", "stopped": name}

    def reap_idle(self, older_than_seconds: int = 3600) -> int:
        """Remove workspace containers nothing has touched for a while.

        A container per project is cheap but not free, and a server left running
        for a week is a server nobody is watching. Driven off Docker's own
        labels rather than in-process state so it still works after a restart.
        """
        removed = 0
        try:
            r = subprocess.run(
                ["docker", "ps", "-a", "--filter", "label=weave.workspace=1",
                 "--format", "{{.Names}}"],
                capture_output=True, text=True, timeout=20, check=False,
            )
            for name in (r.stdout or "").split():
                last = self._last_used.get(name)
                if last is not None and (time.monotonic() - last) < older_than_seconds:
                    continue
                if last is None and self._container_state(name) == "running":
                    # Started by a previous process. Give it one grace period
                    # rather than killing a build someone is watching.
                    self._last_used[name] = time.monotonic()
                    continue
                subprocess.run(["docker", "rm", "-f", name], capture_output=True,
                               text=True, timeout=60, check=False)
                self._last_used.pop(name, None)
                removed += 1
        except Exception as exc:  # noqa: BLE001
            log.debug("workspace reap failed: %s", exc)
        return removed

    def exec(self, project_id: str, command: str, timeout: int | None = None,
             cancel=None) -> ExecResult:
        """Run a shell command in the project's long-lived container."""
        if not self.enabled:
            return ExecResult(status="unavailable",
                              stderr="workspace execution is not configured (Docker unavailable)")
        if not (command or "").strip():
            return ExecResult(status="error", stderr="empty command")

        timeout = int(timeout or settings.workspace_exec_timeout)
        timeout = max(5, min(timeout, settings.workspace_exec_max_timeout))

        up = self.ensure_container(project_id)
        if up.status != "ok":
            return up
        name = self.container_name(project_id)
        self._last_used[name] = time.monotonic()

        args = ["docker", "exec", "-i", "--user", settings.workspace_user,
                "--workdir", "/workspace", name, "bash", "-lc", command]

        started = time.monotonic()
        try:
            # Popen rather than run(), so a client that disconnects mid-build
            # actually stops the build. `cancel` was accepted and ignored
            # before, which meant closing the tab left an npm install running to
            # completion against a turn nobody was waiting for.
            proc = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
            )
        except FileNotFoundError:
            self._docker = False
            return ExecResult(status="unavailable", stderr="docker is not installed on this host")

        deadline = started + timeout
        while True:
            try:
                stdout, stderr = proc.communicate(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                pass
            if cancel is not None and cancel.is_set():
                proc.kill()
                proc.communicate()
                return ExecResult(status="error", exit_code=130,
                                  stderr="cancelled — the user stopped this turn",
                                  duration_ms=int((time.monotonic() - started) * 1000))
            if time.monotonic() > deadline:
                proc.kill()
                out, err = proc.communicate()
                return ExecResult(
                    status="timeout", exit_code=124,
                    stdout=_tail(out or "", settings.workspace_output_chars),
                    stderr=(_tail(err or "", 2000)
                            + f"\ncommand exceeded the {timeout}s limit"),
                    duration_ms=int((time.monotonic() - started) * 1000),
                )

        return ExecResult(
            status="ok" if proc.returncode == 0 else "error",
            exit_code=proc.returncode or 0,
            # Truncate from the FRONT of long logs: an npm install prints
            # thousands of progress lines and the error is at the end.
            stdout=_tail(stdout or "", settings.workspace_output_chars),
            stderr=_tail(stderr or "", settings.workspace_output_chars),
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    # ------------------------------------------------------------- dev servers

    #: Where a started server's bookkeeping lives inside the workspace. On disk
    #: rather than in memory so a backend restart does not orphan a running
    #: process that nothing then knows how to stop.
    SERVER_STATE = ".weave/server.json"

    def serve(self, project_id: str, command: str, port: int,
              wait_seconds: int = 45) -> dict:
        """Start a long-running dev server and wait until it actually answers.

        Returns both URLs, and they are different on purpose:

          * `url` is on 127.0.0.1 and is what the USER's browser opens — the
            port is published to the host loopback.
          * `internal_url` is `container-name:port` on the Docker network, which
            is how Browserless reaches it to screenshot the running app. A
            headless browser in another container cannot resolve the host's
            loopback, and this is the difference between being able to check the
            app works and having to ask the user to look.

        Waiting for the port matters more than it sounds: a server reports
        "started" long before it has compiled anything, and handing back a URL
        that 502s for ten seconds teaches the user the preview is broken.
        """
        if not self.enabled:
            return {"status": "unavailable",
                    "message": "workspace execution is not configured"}
        if port not in self.DEV_PORTS:
            return {"status": "error",
                    "error": f"port {port} is not published; use one of "
                             f"{', '.join(str(p) for p in self.DEV_PORTS)}"}

        up = self.ensure_container(project_id)
        if up.status != "ok":
            return {"status": "error", "error": up.stderr}

        self.stop_server(project_id)

        name = self.container_name(project_id)
        # Detached, output to a log the model can read back. `setsid` divorces
        # it from the exec session so it survives the command returning.
        # `;` after the mkdir, not `&&`.
        #
        # `A && B & C` backgrounds the whole `A && B` list, so with `&&` the
        # `echo $! > .weave/server.pid` ran immediately — racing the mkdir that
        # was supposed to create the directory it writes into, and losing.
        launch = (
            "mkdir -p .weave; "
            f"setsid nohup bash -lc {_sh_quote(command)} "
            "> .weave/server.log 2>&1 < /dev/null & "
            "echo $! > .weave/server.pid"
        )
        started = self.exec(project_id, launch, timeout=30)
        if started.status not in {"ok"}:
            return {"status": "error", "error": started.stderr or "could not start the server"}

        # Poll from INSIDE the container: the process may bind before the host
        # mapping is usable, and this is the check that matches what Browserless
        # will experience.
        probe = (
            f"for i in $(seq 1 {max(1, wait_seconds)}); do "
            f"  if (echo > /dev/tcp/127.0.0.1/{port}) 2>/dev/null; then echo UP; exit 0; fi; "
            "  sleep 1; "
            "done; echo DOWN; exit 1"
        )
        ready = self.exec(project_id, probe, timeout=wait_seconds + 15)
        logs = self.exec(project_id, "tail -c 4000 .weave/server.log 2>/dev/null || true",
                         timeout=20)

        host_ports = self.ports(project_id)
        host_port = host_ports.get(port)
        state = {"command": command, "port": port, "host_port": host_port}
        self.write_file(project_id, self.SERVER_STATE, json.dumps(state))

        if "UP" not in (ready.stdout or ""):
            return {
                "status": "error",
                "error": f"the server did not start listening on port {port} within "
                         f"{wait_seconds}s",
                "log": _tail(logs.stdout or "", 3000),
                "hint": "Read the log above. A dev server that exits immediately is "
                        "usually a missing dependency or a syntax error.",
            }

        return {
            "status": "ok",
            "port": port,
            "url": f"http://127.0.0.1:{host_port}" if host_port else "",
            "internal_url": f"http://{name}:{port}",
            "log": _tail(logs.stdout or "", 2000),
        }

    def stop_server(self, project_id: str) -> dict:
        """Stop whatever this project last started. Safe to call when nothing is."""
        if not self.enabled:
            return {"status": "unavailable"}
        if self._container_state(self.container_name(project_id)) != "running":
            return {"status": "ok", "stopped": False}
        self.exec(
            project_id,
            "if [ -f .weave/server.pid ]; then "
            "  kill -TERM -$(cat .weave/server.pid) 2>/dev/null || "
            "  kill -TERM $(cat .weave/server.pid) 2>/dev/null || true; "
            "  rm -f .weave/server.pid; fi",
            timeout=20,
        )
        return {"status": "ok", "stopped": True}

    def server_status(self, project_id: str) -> dict:
        """What is running, if anything — for the preview panel."""
        if not self.enabled:
            return {"status": "unavailable", "running": False}
        if self._container_state(self.container_name(project_id)) != "running":
            return {"status": "ok", "running": False}
        state = self.read_file(project_id, self.SERVER_STATE)
        if state.get("status") != "ok":
            return {"status": "ok", "running": False}
        try:
            saved = json.loads(state.get("content") or "{}")
        except ValueError:
            return {"status": "ok", "running": False}
        port = int(saved.get("port") or 0)
        if not port:
            return {"status": "ok", "running": False}
        alive = self.exec(
            project_id,
            f"(echo > /dev/tcp/127.0.0.1/{port}) 2>/dev/null && echo UP || echo DOWN",
            timeout=20,
        )
        running = "UP" in (alive.stdout or "")
        host_port = self.ports(project_id).get(port)
        return {
            "status": "ok",
            "running": running,
            "port": port,
            "url": f"http://127.0.0.1:{host_port}" if (running and host_port) else "",
            "internal_url": f"http://{self.container_name(project_id)}:{port}" if running else "",
            "command": saved.get("command", ""),
        }

    def server_log(self, project_id: str, lines: int = 200) -> dict:
        if not self.enabled:
            return {"status": "unavailable"}
        out = self.exec(project_id, f"tail -n {max(1, min(lines, 2000))} "
                                    ".weave/server.log 2>/dev/null || true", timeout=25)
        return {"status": "ok", "log": _tail(out.stdout or "", 12000)}

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


def _safe_id(value: str) -> str:
    """A Docker-name-safe form of a project id.

    Container names must match [a-zA-Z0-9][a-zA-Z0-9_.-]*. Project ids are hex
    uuids so this is normally a no-op, but a name Docker rejects would fail every
    command in the workspace with an error about the container rather than about
    the work, which is a miserable thing to debug.
    """
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "", str(value or "shared"))
    return (cleaned or "shared")[:48]


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
