"""Shared FastAPI dependencies: current-user resolution and the two rate-limit
buckets (chat vs. sandbox) from architecture 5.3 / 8.
"""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User
from .ratelimit import build_limiter
from .security import decode_access_token

# Chat/analysis and sandbox executions are rate-limited on separate buckets;
# sandbox is stricter because it is the most expensive/dangerous call (8 / 5.3).
#
# `build_limiter` returns a Redis-backed bucket when WEAVE_REDIS_URL is set and
# a per-process one otherwise. That distinction matters as soon as the API runs
# with more than one worker: per-process buckets multiply the configured limit
# by the worker count, silently. See ratelimit.py.
chat_limiter = build_limiter(settings.rate_limit_chat_per_min, namespace="weave:rl:chat")
sandbox_limiter = build_limiter(settings.rate_limit_sandbox_per_min,
                                namespace="weave:rl:sandbox")
anon_limiter = build_limiter(settings.rate_limit_anon_per_min, namespace="weave:rl:anon")
auth_limiter = build_limiter(settings.rate_limit_auth_per_min, namespace="weave:rl:auth")


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = authorization.split(" ", 1)[1]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")
    # WebSocket tickets travel in query strings, where they end up in proxy logs
    # and browser history. They open a socket and nothing else — accepting one
    # here would make that exposure equivalent to leaking a session token.
    if payload.get("scope") == "ws":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "this token is only valid for opening a websocket")
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
    return user


def get_optional_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User | None:
    if not authorization:
        return None
    try:
        return get_current_user(authorization, db)
    except HTTPException:
        return None


def _client_key(request: Request, user: User | None) -> str:
    if user:
        return f"user:{user.id}"
    fwd = request.headers.get("x-forwarded-for")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")
    return f"ip:{ip}"


def enforce_chat_limit(request: Request, user: User = Depends(get_current_user)) -> User:
    allowed, retry = chat_limiter.allow(_client_key(request, user))
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "chat rate limit exceeded",
            headers={"Retry-After": str(int(retry) + 1)},
        )
    return user


def enforce_sandbox_limit(request: Request, user: User = Depends(get_current_user)) -> User:
    allowed, retry = sandbox_limiter.allow(_client_key(request, user))
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "sandbox execution rate limit exceeded",
            headers={"Retry-After": str(int(retry) + 1)},
        )
    return user


def enforce_auth_limit(request: Request) -> None:
    """Throttle the credential endpoints, by CLIENT ADDRESS.

    These were the only routes in the application with no limit of any kind, and
    they are the only ones where calling repeatedly is the attack:

      * `/auth/login` — password guessing, unbounded. Worse than the usual case
        because verification is scrypt: each attempt costs the SERVER 64MB and
        real CPU, so an attacker who is not even trying to get in can exhaust
        the box by trying.
      * `/auth/otp/verify` — a six-digit code has a million values and a
        ten-minute life. Unlimited guesses make that arithmetic, not luck.
      * `/auth/otp/request` — every call sends an SMS that somebody pays for,
        and writes a row nobody deletes.
      * `/auth/register` — account creation as a spam primitive.

    Keyed on the client address rather than on the account, deliberately. Keying
    on the account would let an attacker lock a real user out of their own login
    by failing on their behalf, which converts a brute-force defence into a
    denial-of-service tool.
    """
    key = _client_key(request, None)
    allowed, retry = auth_limiter.allow(key)
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too many attempts — wait a moment and try again",
            headers={"Retry-After": str(int(retry) + 1)},
        )


def get_admin_user(user: User = Depends(get_current_user)) -> User:
    """Admin/ops scope (architecture 4.2 /admin). Gated to the 'admin' role or
    institutional trust tier for the MVP."""
    if user.role != "admin" and user.trust_tier != "institutional":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin access required")
    return user


def enforce_anon_limit(request: Request, user: User | None = Depends(get_optional_user)):
    allowed, retry = anon_limiter.allow(_client_key(request, user))
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "rate limit exceeded",
            headers={"Retry-After": str(int(retry) + 1)},
        )
    return user
