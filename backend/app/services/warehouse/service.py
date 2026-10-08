"""Analytics warehouse for mass data mining/analysis.

DuckDB runs embedded, out of core SQL directly over the user's dataset. A
ClickHouse setting is reserved for a future measured scale-up, but does not
advertise the tool by itself: there is no ingestion/query contract for it yet.

SQL is a hostile-input surface, so this enforces a read-only guard: SELECT/WITH
only, and file/system/DDL functions are blocked. (In production the whole query
runs inside the sandbox tier; the guard here is defence-in-depth.)
"""
from __future__ import annotations

import re
import math
import threading

from ...storage import storage
from ..sandbox.datasets import CSV_NULL_VALUES, csv_options, read_dataset

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
        return self._duckdb is not None

    def query(self, sql: str, dataset=None, max_rows: int = 200) -> dict:
        ok, reason = _is_read_only(sql)
        if not ok:
            return {"status": "rejected", "error": reason}
        if self._duckdb is None:
            return {"status": "unavailable", "error": "duckdb is not installed"}
        if dataset is None:
            return {"status": "error", "error": "no dataset in context to query (use `data` table)"}
        if getattr(dataset, "status", "ready") != "ready":
            return {"status": "error", "code": "dataset_not_ready",
                    "error": "dataset is not ready; wait for profiling or correct the parsing error"}

        con = None
        timer = None
        try:
            path = storage.local_path(dataset.s3_key)
            suffix = path.suffix.lower()
            con = self._duckdb.connect(database=":memory:")
            con.execute("SET memory_limit = '512MB'")
            con.execute("SET threads = 2")
            if suffix in {".csv", ".tsv"}:
                options = csv_options(path)
                if options["encoding"] in {"utf-8", "utf-8-sig"}:
                    con.read_csv(str(path), delimiter=options["sep"],
                                 sample_size=-1, strict_mode=True, header=True,
                                 na_values=CSV_NULL_VALUES).create_view("source_data")
                    con.execute("CREATE TABLE data AS SELECT * FROM source_data")
                    con.execute("DROP VIEW source_data")
                else:
                    # DuckDB does not ship legacy encoding support by default.
                    con.register("source_data", read_dataset(path))
                    con.execute("CREATE TABLE data AS SELECT * FROM source_data")
                    con.unregister("source_data")
            elif suffix in {".xlsx", ".xls", ".json", ".parquet"}:
                df = read_dataset(path)
                con.register("data", df)
            else:
                return {"status": "error", "error": f"unsupported dataset format {suffix}"}

            # Regex checks alone miss aliases/extensions and replacement scans.
            # Materialize the one trusted file, then disable every external scan
            # for the untrusted query and prevent it from restoring settings.
            con.execute("SET enable_external_access = false")
            con.execute("SET lock_configuration = true")
            timer = threading.Timer(30, con.interrupt)
            timer.daemon = True
            timer.start()
            limit = max(1, min(int(max_rows), 1000))
            cursor = con.execute(f"SELECT * FROM ({sql.strip().rstrip(';')}) AS weave_result LIMIT ?",
                                 [limit + 1])
            columns = [str(item[0]) for item in cursor.description]
            rows = cursor.fetchall()
            truncated = len(rows) > limit
            rows = rows[:limit]
            return {
                "status": "ok",
                "columns": columns,
                "rows": [[_public_value(value) for value in row] for row in rows],
                "row_count": len(rows), "truncated": truncated,
                "dataset_id": getattr(dataset, "id", None),
                "dataset_name": getattr(dataset, "original_filename", path.name),
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        finally:
            if timer is not None:
                timer.cancel()
            if con is not None:
                con.close()


def _public_value(value):
    from datetime import date, datetime, time
    from decimal import Decimal
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (list, tuple)):
        return [_public_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _public_value(item) for key, item in value.items()}
    if isinstance(value, bytes):
        import base64
        return base64.b64encode(value).decode("ascii")
    return value


_service: WarehouseService | None = None


def get_warehouse() -> WarehouseService:
    global _service
    if _service is None:
        _service = WarehouseService()
    return _service
