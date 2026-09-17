"""The production schema must be reproducible without create_all side effects."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


def _run(backend: Path, database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update({
        "WEAVE_DATABASE_URL": database_url,
        "WEAVE_ENVIRONMENT": "production",
        "WEAVE_DEBUG": "false",
        "WEAVE_SECRET_KEY": "migration-test-secret-that-is-long-and-random-enough",
        "WEAVE_ANALYSIS_EXECUTION_ENABLED": "false",
    })
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=backend,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


def test_initial_migration_upgrades_and_downgrades_clean_database(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "migration.db"
    url = f"sqlite:///{db_path.as_posix()}"

    upgraded = _run(backend, url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr

    engine = create_engine(url)
    names = set(inspect(engine).get_table_names())
    assert {"alembic_version", "users", "projects", "messages", "source_chunk_fts"} <= names
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    engine.dispose()

    downgraded = _run(backend, url, "downgrade", "base")
    assert downgraded.returncode == 0, downgraded.stderr
    engine = create_engine(url)
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    engine.dispose()
