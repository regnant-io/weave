"""Measure bilingual hybrid-retrieval recall and latency on a populated DB.

Run against staging Postgres after seeding public sources:
  python -m app.seed.seed
  python -m eval.benchmark_retrieval --min-recall 0.75 --max-p95-ms 250

SQLite can be used for a developer smoke run with ``--allow-sqlite``. Its timing
is not a production release result because it uses the Python dense fallback.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-recall", type=float, default=0.75)
    parser.add_argument("--max-p95-ms", type=float, default=250.0)
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--allow-sqlite", action="store_true")
    args = parser.parse_args()

    from app.config import settings
    from app.db import SessionLocal
    from app.services.retrieval import get_retrieval_service

    if settings.is_sqlite and not args.allow_sqlite:
        print("refusing to label SQLite fallback timing as a production benchmark")
        return 2

    cases = json.loads(Path(__file__).with_name("retrievalset.json").read_text("utf-8"))
    db = SessionLocal()
    latencies: list[float] = []
    hits = 0
    try:
        retrieval = get_retrieval_service()
        for case in cases:
            started = time.perf_counter()
            rows = retrieval.search(db, case["query"], case["language"], top_k=args.top_k)
            elapsed = (time.perf_counter() - started) * 1000
            latencies.append(elapsed)
            hit = any(case["expected_title"].lower() in row["title"].lower() for row in rows)
            hits += int(hit)
            print(f"[{'HIT' if hit else 'MISS'}] {case['id']}: {elapsed:.1f} ms")
    finally:
        db.close()

    recall = hits / len(cases)
    ordered = sorted(latencies)
    p95 = ordered[max(0, int(len(ordered) * 0.95 + 0.999) - 1)]
    result = {
        "database": "sqlite" if settings.is_sqlite else "postgresql",
        "cases": len(cases), "recall_at_k": recall, "top_k": args.top_k,
        "p50_ms": statistics.median(latencies), "p95_ms": p95,
    }
    print(json.dumps(result, indent=2))
    return 0 if recall >= args.min_recall and p95 <= args.max_p95_ms else 1


if __name__ == "__main__":
    raise SystemExit(main())
