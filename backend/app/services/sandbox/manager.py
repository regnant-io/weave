"""Sandbox Manager (architecture section 8.2).

Owns the full execution lifecycle for untrusted, model-generated code:

  1. static pre-check (reject obviously out-of-scope code cheaply)
  2. pull an isolated workspace (fresh per execution — never reused across users)
  3. attach a READ-ONLY private copy of the one dataset
  4. inject the code and execute under strict resource + wall-clock limits with
     no network
  5. capture stdout/stderr/exit + files written to /output (nothing else)
  6. destroy the workspace
  7. return a structured result

Backends:
  * ``subprocess`` (default here) — a locked-down child Python process. Correct
    for a dev/prototype host (architecture 13, v0 tier).
  * ``firecracker`` — production backend; each run is a fresh microVM. Stubbed
    with the exact same public contract so it is a drop-in swap (8.5).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ...config import settings
from .precheck import static_precheck

_RUNNER = Path(__file__).with_name("runner.py")


@dataclass
class OutputFile:
    name: str
    data_b64: str
    mime: str
    bytes: int


@dataclass
class SandboxResult:
    status: str  # ok | error | rejected | timeout
    stdout: str = ""
    stderr: str = ""
    output_files: list[OutputFile] = field(default_factory=list)
    execution_time_ms: int = 0
    peak_memory_kb: int = 0
    violations: list[str] = field(default_factory=list)
    code_hash: str = ""
    result_hash: str = ""

    def to_public_dict(self) -> dict:
        d = asdict(self)
        # output file bytes are returned via storage keys by the Analysis Service;
        # keep the raw b64 out of the default public dict.
        d["output_files"] = [
            {"name": f.name, "mime": f.mime, "bytes": f.bytes} for f in self.output_files
        ]
        return d


_MIME_BY_EXT = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml", ".csv": "text/csv", ".txt": "text/plain",
    ".json": "application/json", ".html": "text/html",
}


class SandboxManager:
    def __init__(self) -> None:
        self.backend = settings.sandbox_backend

    # -- public API -----------------------------------------------------------

    def run(
        self,
        code: str,
        dataset_path: Path | None = None,
        heavy: bool = False,
        memory_mb: int | None = None,
    ) -> SandboxResult:
        code_hash = hashlib.sha256(code.encode()).hexdigest()

        # (1) static pre-check — belt and suspenders (architecture 8.4.1)
        pre = static_precheck(code)
        if not pre.ok:
            return SandboxResult(
                status="rejected", violations=pre.violations, code_hash=code_hash,
                stderr="Rejected by static pre-check:\n- " + "\n- ".join(pre.violations),
            )

        if self.backend == "firecracker":  # pragma: no cover - prod path
            return self._run_firecracker(code, dataset_path, heavy, memory_mb, code_hash)
        return self._run_subprocess(code, dataset_path, heavy, memory_mb, code_hash)

    # -- subprocess backend ---------------------------------------------------

    def _run_subprocess(
        self, code: str, dataset_path: Path | None, heavy: bool,
        memory_mb: int | None, code_hash: str,
    ) -> SandboxResult:
        timeout = settings.sandbox_heavy_timeout_seconds if heavy else settings.sandbox_timeout_seconds
        mem = memory_mb or settings.sandbox_memory_mb

        # (2) fresh isolated workspace
        workspace = Path(tempfile.mkdtemp(prefix="weave_sbx_"))
        input_dir = workspace / "input"
        output_dir = workspace / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        code_file = workspace / "code.py"
        result_file = workspace / "_result.json"
        manifest_file = workspace / "_manifest.json"

        try:
            # (3) read-only private copy of the single dataset
            if dataset_path is not None and Path(dataset_path).exists():
                dst = input_dir / Path(dataset_path).name
                shutil.copy2(dataset_path, dst)
                dst.chmod(0o444)

            code_file.write_text(code, encoding="utf-8")
            manifest_file.write_text(json.dumps({
                "input_dir": str(input_dir),
                "output_dir": str(output_dir),
                "code_file": str(code_file),
                "result_file": str(result_file),
                "memory_mb": mem,
                "cpu_seconds": timeout,
                "max_output_files": settings.sandbox_max_output_files,
            }), encoding="utf-8")

            # (4) execute with a hard wall-clock timeout and a scrubbed environment
            #     (no inherited network/credential env; PYTHONPATH pinned).
            # Shared matplotlib font-cache dir: a pure cache (no user data), so it
            # is safe to persist across runs and avoids a slow font-cache rebuild
            # on every execution (which could otherwise brush the wall-clock limit).
            mpl_cache = Path(settings.storage_local_dir).parent / "mplcache"
            mpl_cache.mkdir(parents=True, exist_ok=True)
            env = {
                "PATH": "/usr/local/bin:/usr/bin:/bin",  # for any tool matplotlib shells out to
                "MPLBACKEND": "Agg",
                "MPLCONFIGDIR": str(mpl_cache),
                "PYTHONDONTWRITEBYTECODE": "1",
                "HOME": str(workspace),
                "TMPDIR": str(workspace),
                "TEMP": str(workspace),
                "TMP": str(workspace),
            }
            started = time.monotonic()
            status = "ok"
            try:
                # -I = isolated mode (ignore PYTHON* env + user site-dir) but still
                #      run site.py so the pinned scientific stack in site-packages
                #      is importable. (Do NOT add -S; it would hide site-packages.)
                subprocess.run(
                    [sys.executable, "-I", str(_RUNNER), str(manifest_file)],
                    cwd=str(workspace),
                    env=env,
                    timeout=timeout + 5,  # grace over the in-VM CPU limit
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    check=False,
                    **self._posix_preexec(),
                )
            except subprocess.TimeoutExpired:
                status = "timeout"
            elapsed_ms = int((time.monotonic() - started) * 1000)

            # (5) collect structured result
            if status == "timeout":
                return SandboxResult(
                    status="timeout", execution_time_ms=elapsed_ms, code_hash=code_hash,
                    stderr=f"Execution exceeded the {timeout}s time limit and was terminated.",
                )
            if not result_file.exists():
                return SandboxResult(
                    status="error", execution_time_ms=elapsed_ms, code_hash=code_hash,
                    stderr="Sandbox produced no result (the process crashed before completing).",
                )

            raw = json.loads(result_file.read_text(encoding="utf-8"))
            outputs = self._collect_outputs(output_dir)
            result = SandboxResult(
                status=raw.get("status", "ok"),
                stdout=raw.get("stdout", "")[: 200_000],
                stderr=raw.get("stderr", "")[: 200_000],
                output_files=outputs,
                execution_time_ms=elapsed_ms,
                code_hash=code_hash,
            )
            result.result_hash = hashlib.sha256(
                (result.stdout + result.stderr + "".join(o.name for o in outputs)).encode()
            ).hexdigest()
            return result
        finally:
            # (6) destroy the workspace (never reused)
            shutil.rmtree(workspace, ignore_errors=True)

    def _collect_outputs(self, output_dir: Path) -> list[OutputFile]:
        import base64

        files: list[OutputFile] = []
        total = 0
        for p in sorted(output_dir.iterdir()):
            if not p.is_file():
                continue
            data = p.read_bytes()
            total += len(data)
            # (architecture 8.4.4) output size cap — skip anything over the limit
            if len(data) > settings.sandbox_output_max_bytes or total > settings.sandbox_output_max_bytes:
                continue
            files.append(OutputFile(
                name=p.name,
                data_b64=base64.b64encode(data).decode("ascii"),
                mime=_MIME_BY_EXT.get(p.suffix.lower(), "application/octet-stream"),
                bytes=len(data),
            ))
            if len(files) >= settings.sandbox_max_output_files:
                break
        return files

    def _posix_preexec(self) -> dict:
        """On POSIX, start the child in its own session so a timeout kill reaps
        the whole group. `start_new_session=True` performs setsid() itself — do
        NOT also pass preexec_fn=os.setsid (the second setsid would EPERM). On
        Windows this is a no-op."""
        if sys.platform == "win32":
            return {}
        return {"start_new_session": True}

    # -- firecracker backend (production) ------------------------------------

    def _run_firecracker(self, *args, **kwargs) -> SandboxResult:  # pragma: no cover
        raise NotImplementedError(
            "Firecracker backend: boot a warm microVM from the pool, attach a "
            "read-only COW block device for the dataset, inject runner.py over the "
            "control-plane vsock, enforce cgroup/jailer limits, then destroy the VM. "
            "The runner.py harness and this SandboxResult contract are identical to "
            "the subprocess backend — only transport changes."
        )


_manager: SandboxManager | None = None


def get_sandbox_manager() -> SandboxManager:
    global _manager
    if _manager is None:
        _manager = SandboxManager()
    return _manager
