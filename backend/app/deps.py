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
