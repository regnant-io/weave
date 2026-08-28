"""Usage analytics for the welcome screen.

Everything here is derived from rows the app already writes — there is no
tracking layer and no event pipeline. The point is to make a returning user's
own history legible (how much they've done, when they work, what they use)
rather than to measure them.

All computation is per-caller and scoped to their own projects.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import AnalysisRun, Dataset, Message, Project, Thread, User

router = APIRouter()

#: Same ratio the orchestrator budgets with, so the "tokens" figure the user
#: sees is the same estimate the context meter is drawn against.
CHARS_PER_TOKEN = 3.6


def _as_utc(dt: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; Postgres hands back aware ones.

    Comparing the two raises, so everything is normalised on the way in rather
    than at each comparison site.
    """
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


@router.get("/stats")
def usage_stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    project_ids = [
        r[0] for r in db.query(Project.id).filter(Project.user_id == user.id).all()
    ]
    if not project_ids:
        return _empty()

    rows = (
        db.query(Message.role, Message.content_en, Message.content_sw, Message.created_at)
        .filter(Message.project_id.in_(project_ids))
        .all()
    )

    total_messages = len(rows)
    user_messages = sum(1 for r in rows if r[0] == "user")
    total_chars = sum(len(r[1] or "") or len(r[2] or "") for r in rows)
    total_tokens = int(total_chars / CHARS_PER_TOKEN)

    # Active days, streaks and peak hour, all from message timestamps.
    days: set[str] = set()
    hours: Counter[int] = Counter()
    weekday: Counter[int] = Counter()
    for _role, _en, _sw, created in rows:
        ts = _as_utc(created)
        if ts is None:
            continue
        days.add(ts.strftime("%Y-%m-%d"))
        hours[ts.hour] += 1
        weekday[ts.weekday()] += 1

    current_streak, longest_streak = _streaks(days)

    threads = db.query(func.count(Thread.id)).filter(
        Thread.project_id.in_(project_ids)
    ).scalar() or 0
    datasets = db.query(func.count(Dataset.id)).filter(
        Dataset.project_id.in_(project_ids)
    ).scalar() or 0

    # Favourite model: tool_calls don't record it, so the analysis-run count is
    # the honest proxy for "how much real work was executed".
    analyses = (
        db.query(func.count(AnalysisRun.id))
        .join(Message, AnalysisRun.message_id == Message.id)
        .filter(Message.project_id.in_(project_ids))
        .scalar() or 0
    )

    tools: Counter[str] = Counter()
    for msg in (
        db.query(Message.tool_calls)
        .filter(Message.project_id.in_(project_ids), Message.role == "assistant")
        .all()
    ):
        for call in (msg[0] or []):
            if isinstance(call, dict) and call.get("name"):
                tools[str(call["name"])] += 1

    peak_hour = hours.most_common(1)[0][0] if hours else None
    last_active = max((_as_utc(r[3]) for r in rows if r[3]), default=None)

    return {
        "projects": len(project_ids),
        "sessions": int(threads) or len(project_ids),
        "messages": total_messages,
        "prompts": user_messages,
        "total_tokens": total_tokens,
        "active_days": len(days),
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "peak_hour": peak_hour,
        "busiest_weekday": weekday.most_common(1)[0][0] if weekday else None,
        "favourite_model": _favourite_model(),
        "datasets": int(datasets),
        "analyses": int(analyses),
        "top_tools": [{"name": n, "count": c} for n, c in tools.most_common(5)],
        "last_active": last_active.isoformat() if last_active else None,
        "activity": _activity_series(days),
    }


def _favourite_model() -> str:
    """The model in use.

    Per-message model isn't persisted, so reporting the configured model is the
    truthful answer rather than inventing a distribution from data we never
    recorded.
    """
    from ..runtime import ollama_model
    from ..services.orchestration.llm import get_engine
    engine = get_engine()
    if getattr(engine, "name", "") == "ollama":
        return ollama_model()
    if getattr(engine, "name", "") == "anthropic":
        from ..config import settings
        return settings.model_tier_fast
    return "offline"


def _streaks(days: set[str]) -> tuple[int, int]:
    """Current and longest run of consecutive active days.

    The current streak counts today OR yesterday as still-alive, so opening the
    app in the morning doesn't read as having broken a streak overnight.
    """
    if not days:
        return 0, 0
    parsed = sorted(datetime.strptime(d, "%Y-%m-%d").date() for d in days)

    longest = run = 1
    for prev, cur in zip(parsed, parsed[1:]):
        if (cur - prev).days == 1:
            run += 1
            longest = max(longest, run)
        elif (cur - prev).days > 1:
            run = 1

    today = datetime.now(timezone.utc).date()
    if (today - parsed[-1]).days > 1:
        return 0, longest

    current = 1
    for prev, cur in zip(reversed(parsed[:-1]), reversed(parsed[1:])):
        if (cur - prev).days == 1:
            current += 1
        else:
            break
    return current, max(longest, current)


def _activity_series(days: set[str], weeks: int = 12) -> list[dict]:
    """Per-day active flags for the last N weeks, oldest first."""
    today = datetime.now(timezone.utc).date()
    out = []
    for i in range((weeks * 7) - 1, -1, -1):
        d = today - timedelta(days=i)
        key = d.strftime("%Y-%m-%d")
        out.append({"date": key, "active": key in days})
    return out


def _empty() -> dict:
    return {
        "projects": 0, "sessions": 0, "messages": 0, "prompts": 0, "total_tokens": 0,
        "active_days": 0, "current_streak": 0, "longest_streak": 0,
        "peak_hour": None, "busiest_weekday": None, "favourite_model": _favourite_model(),
        "datasets": 0, "analyses": 0, "top_tools": [], "last_active": None,
        "activity": _activity_series(set()),
    }
