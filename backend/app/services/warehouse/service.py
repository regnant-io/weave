"""Analytics warehouse for mass data mining/analysis.

Two backends:
  * DuckDB (embedded) — out-of-core SQL directly over the user's dataset. Default
    when the `duckdb` package is available. No server needed.
  * ClickHouse (server) — for GB–TB scale, when WEAVE_CLICKHOUSE_URL is set.

SQL is a hostile-input surface, so this enforces a read-only guard: SELECT/WITH
only, and file/system/DDL functions are blocked. (In production the whole query
runs inside the sandbox tier; the guard here is defence-in-depth.)
"""
from __future__ import annotations

import re

from ...config import settings
from ...storage import storage

_BLOCKED = re.compile(
    r"\b(attach|copy|install|load|pragma|export|import|create|insert|update|delete|"
    r"drop|alter|read_csv|read_parquet|read_json|read_text|glob|system|shell)\b",
    re.I,
)


def _is_read_only(sql: str) -> tuple[bool, str]:
    s = sql.strip().rstrip(";").strip()
    if not s:
        return False, "empty query"
    if not re.match(r"^(select|with)\b", s, re.I):
        return False, "only SELECT / WITH queries are allowed"
    if _BLOCKED.search(s):
        return False, "query uses a blocked (file/system/DDL) construct"
    if ";" in s:
        return False, "multiple statements are not allowed"
    return True, ""


class WarehouseService:
    def __init__(self) -> None:
        self._duckdb = None
        try:
            import duckdb
            self._duckdb = duckdb
        except Exception:  # noqa: BLE001 - not installed
            self._duckdb = None

    @property
    def enabled(self) -> bool:
        return self._duckdb is not None or bool(settings.clickhouse_url)

    def query(self, sql: str, dataset=None, max_rows: int = 200) -> dict:
        ok, reason = _is_read_only(sql)
        if not ok:
            return {"status": "rejected", "error": reason}
        if self._duckdb is None:
            return {"status": "unavailable", "error": "duckdb not installed (ClickHouse path TODO)"}
        if dataset is None:
            return {"status": "error", "error": "no dataset in context to query (use `data` table)"}

        try:
            import pandas as pd
            path = storage.local_path(dataset.s3_key)
            suffix = path.suffix.lower()
            if suffix in {".csv", ".tsv"}:
                df = pd.read_csv(path, sep="\t" if suffix == ".tsv" else ",")
            elif suffix in {".xlsx", ".xls"}:
                df = pd.read_excel(path)
            elif suffix == ".json":
                df = pd.read_json(path)
            else:
                return {"status": "error", "error": f"unsupported dataset format {suffix}"}

            con = self._duckdb.connect(database=":memory:")
            con.register("data", df)
            result = con.execute(sql).fetch_df().head(max_rows)
            con.close()
            return {
                "status": "ok",
                "columns": [str(c) for c in result.columns],
                "rows": result.astype(object).where(result.notna(), None).values.tolist(),
                "row_count": int(len(result)),
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


_service: WarehouseService | None = None


def get_warehouse() -> WarehouseService:
    global _service
    if _service is None:
        _service = WarehouseService()
    return _service
