"""Lightweight dataset profiling (architecture 3, step 1: a profiling job).

Runs on upload to populate `Dataset.column_profile` so the Orchestration Service
can hand the model a schema/profile as context without shipping the raw data.
Degrades gracefully if pandas is unavailable on the host.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def profile_dataset(path: Path) -> dict[str, Any]:
    try:
        import numpy as np
        import pandas as pd
    except ImportError:  # pragma: no cover - host without the scientific stack
        return {"available": False, "reason": "pandas/numpy not installed on host"}

    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            df = pd.read_csv(path)
        elif suffix == ".tsv":
            df = pd.read_csv(path, sep="\t")
        elif suffix in {".xlsx", ".xls"}:
            df = pd.read_excel(path)
        elif suffix == ".json":
            df = pd.read_json(path)
        else:
            return {"available": False, "reason": f"unsupported format {suffix}"}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"could not parse: {exc}"}

    columns = []
    for name in df.columns:
        col = df[name]
        dtype = str(col.dtype)
        info: dict[str, Any] = {
            "name": str(name),
            "dtype": dtype,
            "non_null": int(col.notna().sum()),
            "null": int(col.isna().sum()),
            "unique": int(col.nunique(dropna=True)),
        }
        if pd.api.types.is_numeric_dtype(col):
            desc = col.describe()
            info["kind"] = "numeric"
            info["stats"] = {
                "mean": _f(desc.get("mean")),
                "std": _f(desc.get("std")),
                "min": _f(desc.get("min")),
                "q25": _f(desc.get("25%")),
                "median": _f(desc.get("50%")),
                "q75": _f(desc.get("75%")),
                "max": _f(desc.get("max")),
            }
        elif pd.api.types.is_datetime64_any_dtype(col):
            info["kind"] = "datetime"
        else:
            info["kind"] = "categorical"
            top = col.astype(str).value_counts().head(5)
            info["top_values"] = [{"value": str(k), "count": int(v)} for k, v in top.items()]
        columns.append(info)

    return {
        "available": True,
        "row_count": int(len(df)),
        "column_count": int(df.shape[1]),
        "columns": columns,
        "memory_bytes": int(df.memory_usage(deep=True).sum()),
    }


def _f(v) -> float | None:
    try:
        import math
        f = float(v)
        return None if math.isnan(f) else round(f, 6)
    except (TypeError, ValueError):
        return None
