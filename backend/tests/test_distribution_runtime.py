"""Regression checks for the Python CLI shipped with the desktop runtime."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def _python_tool(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    backend = Path(__file__).resolve().parents[1]
    return subprocess.run(
        [sys.executable, "-m", "app.desktop_entry", "weave-python", *args],
        cwd=cwd, env={**os.environ, "PYTHONPATH": str(backend)},
        capture_output=True, text=True, timeout=30,
    )


def test_desktop_python_supports_version_and_unbuffered_script(tmp_path):
    version = _python_tool(tmp_path, "--version")
    assert version.returncode == 0, version.stderr
    assert version.stdout.startswith("Python ")
    (tmp_path / "helper.py").write_text("VALUE = 42\n", encoding="utf-8")
    script = tmp_path / "main.py"
    script.write_text("import helper; print(helper.VALUE)\n", encoding="utf-8")
    result = _python_tool(tmp_path.parent, "-u", "-B", str(script))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "42"
    assert not (tmp_path / "__pycache__").exists()


def test_desktop_python_checks_local_modules_and_propagates_failure(tmp_path):
    (tmp_path / "helper.py").write_text("VALUE = 42\n", encoding="utf-8")
    (tmp_path / "check.py").write_text("import helper; assert helper.VALUE == 42\n", encoding="utf-8")
    result = _python_tool(tmp_path, "-m", "check")
    assert result.returncode == 0, result.stderr
    bad_option = _python_tool(tmp_path, "--unknown")
    assert bad_option.returncode == 2
    assert "unsupported Python option" in bad_option.stderr
    failure = _python_tool(tmp_path, "-c", "raise SystemExit(7)")
    assert failure.returncode == 7


def test_desktop_posix_shell_preserves_tool_path(monkeypatch):
    from app.services.workspace import service

    monkeypatch.setattr(service.os, "name", "posix")
    assert service.WorkspaceService()._native_args("node --version") == [
        "/bin/sh", "-c", "node --version",
    ]


def test_workspace_recovers_after_docker_becomes_available(monkeypatch):
    from app.services.workspace import service

    monkeypatch.setattr(service.settings, "environment", "dev")
    monkeypatch.setattr(service.settings, "workspace_enabled", True)
    workspace = service.WorkspaceService()
    availability = iter([False, True])
    monkeypatch.setattr(workspace, "_probe_docker", lambda: next(availability))
    assert workspace.enabled is False
    workspace._docker_checked_at -= 6
    assert workspace.enabled is True
    # The healthy cache prevents probing on every tool schema/request.
    assert workspace.enabled is True


def test_native_preview_rejects_another_server_on_its_port(tmp_path, monkeypatch):
    import socket
    from app.services.workspace import service

    monkeypatch.setattr(service.settings, "environment", "desktop")
    monkeypatch.setattr(service.settings, "workspace_enabled", True)
    workspace = service.WorkspaceService()
    workspace.root = tmp_path
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        monkeypatch.setattr(workspace, "DEV_PORTS", [port])
        result = workspace.serve("project", "invalid-command-that-must-not-run", port)
    assert result["status"] == "error"
    assert "already in use" in result["error"]
    assert not workspace._native_servers


def test_native_git_preserves_ignores_and_reports_bad_references(tmp_path):
    import shutil
    import pytest
    from app.services.tools.workspace import _native_git
    from app.services.workspace.service import WorkspaceService

    if not shutil.which("git"):
        pytest.skip("Git is an optional desktop dependency")
    workspace = WorkspaceService()
    workspace.root = tmp_path
    root = workspace.project_dir("git-project")
    (root / ".gitignore").write_text(".env\n", encoding="utf-8")
    assert _native_git(workspace, "git-project", "status", {})["status"] == "ok"
    assert (root / ".gitignore").read_text(encoding="utf-8") == ".env\n"
    assert _native_git(workspace, "git-project", "diff", {"ref": "missing-ref"})["status"] == "error"
    assert _native_git(workspace, "git-project", "diff", {"ref": "--no-index"})["status"] == "error"


def test_windows_sandbox_keeps_system_runtime_and_private_config_path(monkeypatch):
    import json
    from app.services.sandbox import manager

    monkeypatch.setattr(manager.sys, "platform", "win32")
    monkeypatch.setenv("SystemRoot", "C:\\Windows")
    monkeypatch.setenv("WEAVE_SECRET_KEY", "must-not-enter-sandbox")

    def execute(command, **kwargs):
        env = kwargs["env"]
        assert env["SystemRoot"] == "C:\\Windows"
        assert "System32" in env["PATH"]
        assert "WEAVE_SECRET_KEY" not in env
        manifest = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
        assert env["WEAVE_DATA_DIR"] == str(Path(manifest["input_dir"]).parent)
        Path(manifest["result_file"]).write_text(json.dumps({"status": "ok", "stdout": "42"}))
        return manager.subprocess.CompletedProcess(command, 0, stderr=b"")

    monkeypatch.setattr(manager.subprocess, "run", execute)
    assert manager.SandboxManager().run("print(42)").stdout == "42"


def test_sandbox_crash_surfaces_interpreter_stderr(monkeypatch):
    from app.services.sandbox import manager

    monkeypatch.setattr(manager.subprocess, "run", lambda command, **kwargs:
                        manager.subprocess.CompletedProcess(command, 1, stderr=b"runner initialization failed"))
    result = manager.SandboxManager().run("print(42)")
    assert result.status == "error"
    assert "runner initialization failed" in result.stderr
