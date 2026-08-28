"""Sandbox tests — the integration suite architecture 12 requires: real sandboxed
execution against known-good and known-bad code samples."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.services.sandbox import get_sandbox_manager
from app.services.sandbox.precheck import static_precheck


# --- static pre-check (architecture 8.4.1) ---

def test_precheck_allows_clean_analysis():
    code = "import pandas as pd\ndf = weave_io.load_dataset()\nprint(df.describe())"
    assert static_precheck(code).ok


@pytest.mark.parametrize("bad", [
    "import os\nos.system('ls')",
    "import subprocess",
    "import socket",
    "open('/etc/passwd').read()",
    "().__class__.__bases__",
    "eval('1+1')",
    "__import__('os')",
])
def test_precheck_rejects_dangerous_code(bad):
    result = static_precheck(bad)
    assert not result.ok
    assert result.violations


# --- end-to-end execution (known-good / known-bad) ---

def _sample_csv() -> Path:
    d = Path(tempfile.mkdtemp())
    p = d / "data.csv"
    p.write_text("a,b\n1,2\n3,4\n5,6\n")
    return p


def test_known_good_code_executes_and_captures_output():
    mgr = get_sandbox_manager()
    code = (
        "df = weave_io.load_dataset()\n"
        "print('rows', len(df))\n"
        "print('sum_a', int(df['a'].sum()))\n"
        "weave_io.save_output(df.describe().reset_index(), 'summary.csv')\n"
    )
    result = mgr.run(code, dataset_path=_sample_csv())
    assert result.status == "ok", result.stderr
    assert "rows 3" in result.stdout
    assert "sum_a 9" in result.stdout
    assert any(f.name == "summary.csv" for f in result.output_files)


def test_known_good_code_generates_chart():
    mgr = get_sandbox_manager()
    code = (
        "import matplotlib.pyplot as plt\n"
        "df = weave_io.load_dataset()\n"
        "ax = df.plot(kind='bar')\n"
        "weave_io.save_output(ax.figure, 'chart.png')\n"
    )
    result = mgr.run(code, dataset_path=_sample_csv())
    assert result.status == "ok", result.stderr
    charts = [f for f in result.output_files if f.name == "chart.png"]
    assert charts and charts[0].bytes > 0
    assert charts[0].mime == "image/png"


def test_known_bad_code_rejected_by_precheck_before_execution():
    mgr = get_sandbox_manager()
    result = mgr.run("import os\nos.system('echo pwned')", dataset_path=_sample_csv())
    assert result.status == "rejected"
    assert result.violations


def test_runtime_error_is_isolated_not_raised():
    mgr = get_sandbox_manager()
    result = mgr.run("raise ValueError('boom')", dataset_path=_sample_csv())
    assert result.status == "error"
    assert "ValueError" in result.stderr


def test_network_import_blocked_at_runtime():
    # urllib passes an ast import check only if allowed; precheck blocks it, but
    # even the guarded __import__ inside the runner would refuse it.
    mgr = get_sandbox_manager()
    result = mgr.run("import urllib.request", dataset_path=_sample_csv())
    assert result.status == "rejected"
