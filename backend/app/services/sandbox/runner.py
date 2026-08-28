"""In-sandbox execution harness.

This file is the ONLY thing that runs inside the isolated process. It is executed
as a fresh `python runner.py <manifest.json>` for every request (architecture 8.1:
each execution gets a fresh environment, never reused across users).

It implements:
  * the structured I/O contract (architecture 8.4 item 2): user code reads data
    only via `weave_io.load_dataset()` and writes only via `weave_io.save_output()`
  * resource limits (architecture 8.2 step 4): address-space + CPU rlimits on POSIX
  * a restricted builtins namespace: no open/exec/eval/__import__ reach user code
  * capture of stdout/stderr/exit and files written to the /output directory

The process is spawned by manager.py with:
  * network fully disabled (no sockets are importable past the precheck; the
    manager additionally runs it with no inherited network-capable handles)
  * a read-only input directory holding a private copy of the one dataset
  * an empty output directory that is the only writable surface it returns

NOTE: On a production Linux host this same harness runs *inside a Firecracker
microVM* (architecture 8.1). On this dev host it runs as a locked-down
subprocess. The harness code is identical either way; only manager.py's backend
changes.
"""
from __future__ import annotations

import builtins as _builtins
import contextlib
import io
import json
import sys
import traceback
import types
from pathlib import Path


def _apply_resource_limits(memory_mb: int, cpu_seconds: int) -> None:
    """POSIX-only best-effort limits for the subprocess backend. On Windows these
    are no-ops; hard per-execution memory capping is the job of the Firecracker /
    cgroup backend in production (architecture 8.2 step 4).

    NB: RLIMIT_AS caps *virtual* address space, and numpy/pandas/matplotlib
    reserve large virtual arenas via mmap on Linux, so a tight AS limit would kill
    legitimate analysis with a spurious MemoryError. We therefore floor the AS
    limit generously — it still catches a runaway multi-GB allocation while
    letting the pinned scientific stack import and run. CPU time + wall-clock
    (enforced by the manager) are the effective bounds here."""
    try:
        import resource  # POSIX only
    except ImportError:
        return
    as_mb = max(memory_mb, 4096)  # generous floor so the scientific stack imports
    nbytes = as_mb * 1024 * 1024
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_AS, (nbytes, nbytes))
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    with contextlib.suppress(ValueError, OSError):
        # limit (not zero — the interpreter itself may need a thread) child procs
        resource.setrlimit(resource.RLIMIT_NPROC, (256, 256))


def _build_weave_io(input_dir: Path, output_dir: Path, max_files: int) -> types.ModuleType:
    """Construct the `weave_io` helper module the user code is allowed to use."""
    mod = types.ModuleType("weave_io")
    state = {"saved": [], "max_files": max_files}

    def _find_dataset(name: str | None) -> Path:
        candidates = sorted(
            p for p in input_dir.iterdir()
            if p.suffix.lower() in {".csv", ".tsv", ".xlsx", ".xls", ".json", ".parquet"}
        )
        if not candidates:
            raise FileNotFoundError("no dataset available in this sandbox")
        if name:
            for c in candidates:
                if c.name == name or c.stem == name:
                    return c
            raise FileNotFoundError(f"dataset {name!r} not found")
        return candidates[0]

    def load_dataset(name: str | None = None):
        """Return the dataset as a pandas DataFrame (read-only copy)."""
        import pandas as pd
        path = _find_dataset(name)
        suffix = path.suffix.lower()
        if suffix in {".csv"}:
            return pd.read_csv(path)
        if suffix in {".tsv"}:
            return pd.read_csv(path, sep="\t")
        if suffix in {".xlsx", ".xls"}:
            return pd.read_excel(path)
        if suffix == ".json":
            return pd.read_json(path)
        if suffix == ".parquet":
            return pd.read_parquet(path)
        raise ValueError(f"unsupported dataset format: {suffix}")

    def save_output(obj, name: str) -> str:
        """Persist a chart / table / text artifact to the sandbox output surface.

        Accepts a matplotlib Figure/Axes, a pandas DataFrame/Series, bytes, or str.
        Returns the output filename actually written.
        """
        if len(state["saved"]) >= state["max_files"]:
            raise RuntimeError(f"output file limit reached ({state['max_files']})")
        safe = "".join(c for c in name if c.isalnum() or c in "._-") or "output"
        target = output_dir / safe

        # matplotlib Figure or Axes
        if hasattr(obj, "savefig"):
            if not target.suffix:
                target = target.with_suffix(".png")
            obj.savefig(target, dpi=110, bbox_inches="tight")
        elif hasattr(obj, "figure") and hasattr(obj.figure, "savefig"):
            if not target.suffix:
                target = target.with_suffix(".png")
            obj.figure.savefig(target, dpi=110, bbox_inches="tight")
        # pandas DataFrame / Series
        elif hasattr(obj, "to_csv"):
            if not target.suffix:
                target = target.with_suffix(".csv")
            obj.to_csv(target, index=False)
        elif isinstance(obj, bytes):
            target.write_bytes(obj)
        else:
            target.write_text(str(obj), encoding="utf-8")

        state["saved"].append(target.name)
        return target.name

    mod.load_dataset = load_dataset
    mod.save_output = save_output
    mod.INPUT_DIR = str(input_dir)
    mod.OUTPUT_DIR = str(output_dir)
    return mod


# Builtins withheld from user code (defense in depth atop the static precheck).
_BLOCKED_BUILTINS = {
    "eval", "exec", "compile", "open", "input", "__import__", "breakpoint",
    "globals", "locals", "vars", "memoryview", "help", "exit", "quit",
}


def _restricted_builtins() -> dict:
    allowed = {}
    for k in dir(_builtins):
        if k in _BLOCKED_BUILTINS:
            continue
        allowed[k] = getattr(_builtins, k)
    # A controlled __import__ that only admits the pinned package set.
    real_import = _builtins.__import__
    allowlist = {
        "pandas", "numpy", "scipy", "statsmodels", "matplotlib", "seaborn",
        "math", "statistics", "json", "datetime", "collections", "itertools",
        "functools", "re", "random", "decimal", "fractions", "weave_io",
    }

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        root = name.split(".")[0]
        if root not in allowlist:
            raise ImportError(f"import of {name!r} is not permitted in the sandbox")
        return real_import(name, globals, locals, fromlist, level)

    allowed["__import__"] = guarded_import
    return allowed


def main() -> int:
    manifest_path = Path(sys.argv[1])
    manifest = json.loads(manifest_path.read_text())

    input_dir = Path(manifest["input_dir"])
    output_dir = Path(manifest["output_dir"])
    code = Path(manifest["code_file"]).read_text(encoding="utf-8")
    result_file = Path(manifest["result_file"])
    memory_mb = int(manifest.get("memory_mb", 512))
    cpu_seconds = int(manifest.get("cpu_seconds", 30))
    max_files = int(manifest.get("max_output_files", 12))

    _apply_resource_limits(memory_mb, cpu_seconds)

    # Non-interactive matplotlib backend before any user import.
    import os
    os.environ["MPLBACKEND"] = "Agg"

    weave_io = _build_weave_io(input_dir, output_dir, max_files)
    sys.modules["weave_io"] = weave_io

    sandbox_globals = {
        "__name__": "__weave_sandbox__",
        "__builtins__": _restricted_builtins(),
        "weave_io": weave_io,
    }

    out_buf, err_buf = io.StringIO(), io.StringIO()
    status = "ok"
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        try:
            compiled = compile(code, "<analysis>", "exec")
            exec(compiled, sandbox_globals)  # noqa: S102 - the whole point of the sandbox
        except SystemExit:
            status = "ok"
        except MemoryError:
            status = "error"
            print("MemoryError: sandbox memory limit exceeded", file=err_buf)
        except BaseException:  # noqa: BLE001 - capture everything, isolate the parent
            status = "error"
            err_buf.write(traceback.format_exc())

    output_files = sorted(p.name for p in output_dir.iterdir()) if output_dir.exists() else []
    result = {
        "status": status,
        "stdout": out_buf.getvalue(),
        "stderr": err_buf.getvalue(),
        "output_files": output_files,
    }
    result_file.write_text(json.dumps(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
