"""Small operational metric sink with Redis aggregation and local fallback."""
from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any

from .config import settings

_lock = threading.Lock()
_local: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
_redis = None


def _client():
    global _redis
    if _redis is False:
        return None
    if _redis is None and settings.redis_url:
        try:
            import redis
            _redis = redis.Redis.from_url(settings.redis_url, decode_responses=True,
                                          socket_timeout=1)
            _redis.ping()
        except Exception:  # noqa: BLE001
            _redis = False
    return _redis if _redis is not False else None


def observe(kind: str, name: str, status: str, duration_ms: float = 0,
            **values: float) -> None:
    key = f"{kind}:{name}:{status}"
    fields = {"count": 1.0, "duration_ms_sum": max(0.0, duration_ms), **values}
    client = _client()
    if client is not None:
        redis_key = f"weave:metrics:{key}"
        pipe = client.pipeline()
        for field, value in fields.items():
            pipe.hincrbyfloat(redis_key, field, float(value))
        pipe.expire(redis_key, 7 * 24 * 60 * 60)
        pipe.execute()
        return
    with _lock:
        for field, value in fields.items():
            _local[key][field] += float(value)


def snapshot() -> dict[str, dict[str, float]]:
    client = _client()
    if client is not None:
        out = {}
        for key in client.scan_iter(match="weave:metrics:*", count=200):
            out[key.removeprefix("weave:metrics:")] = {
                field: float(value) for field, value in client.hgetall(key).items()
            }
        return out
    with _lock:
        return {key: dict(values) for key, values in _local.items()}
