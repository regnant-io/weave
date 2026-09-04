"""Token-bucket rate limiting (architecture 5.3).

TWO BACKENDS, AND WHY THE CHOICE IS LOAD-BEARING

The in-process limiter below is correct for exactly one Python process. That was
the whole deployment for a long time, so it was also the whole story. It stops
being true the moment the API runs with more than one worker — which is the
first thing anyone does when a class of students starts using it at once — and
it fails in the worst available direction: silently, and by letting traffic
through. With four uvicorn workers, each holds its own buckets and each will
independently allow the full per-minute allowance, so the effective limit is
four times what the settings say. Nothing logs it. The dashboard shows the
configured number. Behind a load balancer with several containers it is worse
again, and the number is unknowable.

So when `WEAVE_REDIS_URL` is set the buckets live in Redis, shared by every
worker and every container, and the limit means what it says. When it is not,
the in-process limiter is used and the fact that it is per-process is logged at
startup rather than assumed to be understood.

The algorithm is the same in both: a token bucket refilled at `rate_per_min`,
with a burst allowance. Redis holds the two floats per key and the arithmetic
runs in a Lua script so refill-and-take is atomic — done as two round trips it
is a read-modify-write race, and under exactly the concurrency that makes rate
limiting matter, two callers would both read the same token count and both
spend it.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

log = logging.getLogger("weave.ratelimit")


@dataclass
class _Bucket:
    tokens: float
    last: float


class TokenBucketLimiter:
    """Per-process token bucket. Correct for one worker, and only one."""

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


#: Refill and take, atomically.
#:
#: KEYS[1] = bucket key
#: ARGV    = rate (tokens/sec), capacity, cost, now (unix seconds)
#: returns { allowed (0|1), retry_after_seconds }
_LUA = """
local key      = KEYS[1]
local rate     = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local cost     = tonumber(ARGV[3])
local now      = tonumber(ARGV[4])

local data   = redis.call('HMGET', key, 'tokens', 'last')
local tokens = tonumber(data[1])
local last   = tonumber(data[2])
if tokens == nil then
  tokens = capacity
  last = now
end

local elapsed = now - last
if elapsed < 0 then elapsed = 0 end
tokens = math.min(capacity, tokens + elapsed * rate)

local allowed = 0
local retry = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
else
  if rate > 0 then retry = (cost - tokens) / rate else retry = 60 end
end

redis.call('HMSET', key, 'tokens', tokens, 'last', now)
-- Expire an idle bucket rather than keeping a key per user forever. A full
-- bucket is indistinguishable from no bucket, so this loses nothing: the TTL
-- is the time it takes to refill from empty, plus a margin.
local ttl = 60
if rate > 0 then ttl = math.ceil(capacity / rate) + 60 end
redis.call('EXPIRE', key, ttl)

return { allowed, tostring(retry) }
"""


class RedisTokenBucketLimiter:
    """Token bucket shared across every worker and container via Redis."""

    def __init__(self, client, rate_per_min: int, burst: int | None = None,
                 namespace: str = "weave:rl") -> None:
        self.rate = rate_per_min / 60.0
        self.capacity = float(burst if burst is not None else rate_per_min)
        self._client = client
        self._ns = namespace
        self._script = client.register_script(_LUA)
        #: Falling back per-process is better than failing open, and much better
        #: than 500-ing a request because the cache is briefly unavailable.
        self._local = TokenBucketLimiter(rate_per_min, burst)

    def allow(self, key: str, cost: float = 1.0) -> tuple[bool, float]:
        try:
            allowed, retry = self._script(
                keys=[f"{self._ns}:{key}"],
                args=[self.rate, self.capacity, cost, time.time()],
            )
            return bool(int(allowed)), float(retry)
        except Exception as exc:  # noqa: BLE001 - Redis down must not 500 the API
            # Degrade to the per-process bucket. It under-counts across workers,
            # which is the same weakness as having no Redis at all — acceptable
            # for the length of an outage, and it still stops a single runaway
            # client.
            log.warning("redis rate limiter unavailable (%s); using per-process buckets", exc)
            return self._local.allow(key, cost)


def build_limiter(rate_per_min: int, burst: int | None = None,
                  namespace: str = "weave:rl"):
    """The right limiter for how this instance is actually deployed."""
    from .config import settings

    url = (settings.redis_url or "").strip()
    if not url:
        return TokenBucketLimiter(rate_per_min, burst)
    try:
        import redis  # noqa: PLC0415 - optional dependency

        client = redis.Redis.from_url(url, socket_timeout=1.5,
                                      socket_connect_timeout=1.5,
                                      decode_responses=True)
        client.ping()
        return RedisTokenBucketLimiter(client, rate_per_min, burst, namespace)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "WEAVE_REDIS_URL is set but Redis is not usable (%s). Rate limits are "
            "per-process, so the effective limit is multiplied by the number of "
            "workers.", exc,
        )
        return TokenBucketLimiter(rate_per_min, burst)
