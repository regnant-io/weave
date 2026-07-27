"""Token-bucket rate limiting (architecture 5.3).

Redis-backed in production; an in-process implementation is used when Redis isn't
configured so the gateway still enforces limits with zero external services.
Sandbox execution is rate-limited separately and more strictly than chat
(architecture 5.3 / 8) — see deps.py for the two buckets.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    last: float


class TokenBucketLimiter:
    def __init__(self, rate_per_min: int, burst: int | None = None) -> None:
        self.rate = rate_per_min / 60.0  # tokens per second
        self.capacity = float(burst if burst is not None else rate_per_min)
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, cost: float = 1.0) -> tuple[bool, float]:
        """Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            b = self._buckets.get(key)
            if b is None:
                b = _Bucket(tokens=self.capacity, last=now)
                self._buckets[key] = b
            # refill
            elapsed = now - b.last
            b.tokens = min(self.capacity, b.tokens + elapsed * self.rate)
            b.last = now
            if b.tokens >= cost:
                b.tokens -= cost
                return True, 0.0
            deficit = cost - b.tokens
            return False, deficit / self.rate if self.rate > 0 else 60.0
