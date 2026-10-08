"""One strict dataset reader shared by profiling, SQL and sandbox execution."""
from __future__ import annotations

import csv
import json
from pathlib import Path

CSV_NULL_VALUES = ["", "#N/A", "#N/A N/A", "#NA", "-1.#IND", "-1.#QNAN", "-NaN", "-nan",
                   "1.#IND", "1.#QNAN", "<NA>", "N/A", "NA", "NULL", "NaN", "None", "n/a", "nan", "null"]


def csv_options(path: Path) -> dict:
    with path.open("rb") as source:
        sample = source.read(128 * 1024)
    if sample.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    elif sample.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    else:
        try:
            sample.decode("utf-8", errors="strict")
            encoding = "utf-8"
        except UnicodeDecodeError as exc:
            # A sample can end halfway through a valid UTF-8 character.
            if exc.end == len(sample) and exc.reason == "unexpected end of data":
                encoding = "utf-8"
            else:
                sample.decode("cp1252", errors="strict")
                encoding = "cp1252"
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    # pandas may infer an index and silently consume surplus fields in the
    # first data row. Validate widths before loading to keep calculations honest.
    csv.field_size_limit(16 * 1024 * 1024)
    try:
        _validate_csv(path, encoding, delimiter)
    except UnicodeDecodeError:
        if encoding != "utf-8":
            raise
        # An ASCII-only prefix does not establish the encoding of the entire
        # upload. Legacy CSVs often put accented values in later rows.
        encoding = "cp1252"
        _validate_csv(path, encoding, delimiter)
    return {"sep": delimiter,
            "encoding": encoding, "encoding_errors": "strict",
            "on_bad_lines": "error", "low_memory": False,
            "keep_default_na": False, "na_values": CSV_NULL_VALUES}


def _validate_csv(path: Path, encoding: str, delimiter: str) -> None:
    with path.open(encoding=encoding, errors="strict", newline="") as source:
        reader = csv.reader(source, delimiter=delimiter, strict=True)
        header = next((row for row in reader if row), None)
        if not header:
            raise ValueError("CSV dataset contains no header")
        for row in reader:
            if len(row) > len(header):
                raise ValueError(f"CSV row {reader.line_num} has {len(row)} fields; header has {len(header)}")


def read_dataset(path: Path):
    import pandas as pd

    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv"}:
        return pd.read_csv(path, **csv_options(path))
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, engine="xlrd" if suffix == ".xls" else "openpyxl")
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix == ".json":
        text = path.read_text(encoding="utf-8-sig")
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            if exc.msg != "Extra data":
                raise
            value = [json.loads(line) for line in text.splitlines() if line.strip()]
        if isinstance(value, list):
            if not all(isinstance(row, dict) for row in value):
                raise ValueError("JSON records must be objects")
            return pd.DataFrame.from_records(value)
        if isinstance(value, dict):
            if value and all(not isinstance(v, (list, dict)) for v in value.values()):
                return pd.DataFrame([value])
            return pd.DataFrame(value)
        raise ValueError("JSON dataset must contain records or a column-oriented object")
    raise ValueError(f"unsupported dataset format: {suffix}")
