"""Bounded profiling with explicit scope for every sampled statistic."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from ..sandbox.datasets import csv_options, read_dataset

PROFILE_ROWS = 10_000


def _kind(pd, col) -> str:
    if pd.api.types.is_bool_dtype(col):
        return "categorical"
    if pd.api.types.is_numeric_dtype(col):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(col):
        return "datetime"
    return "categorical"


def profile_dataset(path: Path) -> dict[str, Any]:
    try:
        import pandas as pd
    except ImportError:  # pragma: no cover
        return {"available": False, "reason": "pandas not installed on host"}

    path = Path(path)
    try:
        row_count, nulls, kinds = 0, {}, {}
        if path.suffix.lower() in {".csv", ".tsv"}:
            df = None
            with pd.read_csv(path, chunksize=PROFILE_ROWS, **csv_options(path)) as reader:
                for chunk in reader:
                    if df is None:
                        df = chunk
                    row_count += len(chunk)
                    for name in chunk.columns:
                        nulls[name] = nulls.get(name, 0) + int(chunk[name].isna().sum())
                        if chunk[name].notna().any():
                            kinds.setdefault(name, set()).add(_kind(pd, chunk[name]))
            if df is None:
                raise ValueError("dataset contains no header")
        else:
            full = read_dataset(path)
            row_count = len(full)
            nulls = {name: int(full[name].isna().sum()) for name in full.columns}
            kinds = {name: {_kind(pd, full[name])} for name in full.columns}
            df = full.head(PROFILE_ROWS)

        sampled = row_count > len(df)
        columns = []
        for name in df.columns:
            col = df[name]
            seen = kinds.get(name, set())
            kind = "mixed" if len(seen) > 1 else _kind(pd, col)
            values = col.dropna().map(_value)
            info: dict[str, Any] = {
                "name": str(name), "dtype": "mixed" if kind == "mixed" else str(col.dtype),
                "kind": kind, "non_null": row_count - nulls[name], "null": nulls[name],
                "unique": int(values.nunique()), "statistics_rows": len(df),
                "statistics_scope": "first_rows" if sampled else "full_dataset",
            }
            if kind == "numeric":
                desc = col.describe()
                info["stats"] = {key: _f(desc.get(source)) for key, source in {
                    "mean": "mean", "std": "std", "min": "min", "q25": "25%",
                    "median": "50%", "q75": "75%", "max": "max",
                }.items()}
                info["non_finite"] = int(col.dropna().map(lambda v: not math.isfinite(float(v))).sum())
            elif kind != "datetime":
                top = values.value_counts().head(5)
                info["top_values"] = [{"value": str(k)[:160], "count": int(v)} for k, v in top.items()]
            columns.append(info)
        warnings = []
        if sampled:
            warnings.append(f"Statistics, unique counts and top values describe only the first {len(df)} rows; row and null counts cover the full dataset. Execute analysis for full-data conclusions.")
        if path.suffix.lower() in {".xls", ".xlsx"}:
            warnings.append("Only the first worksheet is loaded.")
        return {"available": True, "row_count": row_count, "column_count": len(df.columns),
                "columns": columns, "sampled": sampled, "statistics_rows": len(df),
                "statistics_scope": "first_rows" if sampled else "full_dataset",
                "memory_bytes": int(df.memory_usage(deep=True).sum()),
                "memory_scope": "profile_sample", "warnings": warnings}
    except Exception as exc:  # noqa: BLE001 - parsing failure is explicit dataset state
        return {"available": False, "reason": f"could not parse: {type(exc).__name__}: {exc}"}


def _value(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str) if isinstance(value, (dict, list)) else str(value)


def _f(value) -> float | None:
    try:
        number = float(value)
        return round(number, 6) if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None
