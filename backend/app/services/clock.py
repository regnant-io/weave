"""What time it is, and how old a web page is.

A model has no clock. Asked for "the latest" anything, it answers from its
training data and presents a year-old state of the world as current. In web
research that has a specific failure: it searches for "latest X 2024" in 2026
because 2024 is the last year it remembers, then reports two-year-old results
as the newest. Two things fix it:

  * the prompt states today's date, and how to resolve "recent", "this year"
    and "last month" against it;
  * every fetched page carries its publication date when the page declares one,
    so the model can see that a source is stale instead of assuming it is not.
"""
from __future__ import annotations

import re
from datetime import datetime


def now() -> datetime:
    """Local wall-clock time with its UTC offset (the machine's own zone)."""
    return datetime.now().astimezone()


def today_iso() -> str:
    return now().date().isoformat()


def date_context(web: bool) -> str:
    """The prompt layer that makes the model time-aware."""
    current = now()
    offset = current.strftime("%z")
    offset = f"UTC{offset[:3]}:{offset[3:]}" if offset else "local time"
    lines = [
        f"CURRENT DATE: {current.strftime('%A, %d %B %Y')}, {current.strftime('%H:%M')} "
        f"({offset}). Year {current.year}.",
        "Your own knowledge stops at your training cutoff, which is earlier than "
        "this. Resolve every relative date against the date above: 'this year' is "
        f"{current.year}, 'last year' is {current.year - 1}, 'recent' means the last "
        "few months before today.",
    ]
    if web:
        lines.append(
            "When searching the web for anything that changes (news, releases, "
            "prices, people's roles, statistics, 'latest' or 'current' anything): "
            f"put {current.year} in the query when recency matters, never an older "
            "year you happen to remember; prefer sources dated close to today; state "
            "the date of the sources you rely on; and when the newest source you "
            "found is old, say so rather than presenting it as current."
        )
    return "\n".join(lines)


_META_DATE = re.compile(
    r"""<meta[^>]+(?:property|name|itemprop)\s*=\s*["'](?:article:published_time|"""
    r"""og:published_time|datePublished|date|dc\.date|dc\.date\.issued|"""
    r"""citation_publication_date|citation_date|pubdate|publish-date|"""
    r"""article:modified_time|dateModified)["'][^>]*>""",
    re.I,
)
_CONTENT = re.compile(r"""content\s*=\s*["']([^"']+)["']""", re.I)
_JSONLD_DATE = re.compile(r'"date(?:Published|Created|Modified)"\s*:\s*"([^"]+)"', re.I)
_TIME_TAG = re.compile(r"""<time[^>]+datetime\s*=\s*["']([^"']+)["']""", re.I)
# Two-digit alternatives first: with `0?[1-9]` first, "2024-11-02" matched the
# month as "1" and came back as 2024-01.
_ISO = re.compile(r"(19|20)\d{2}(?:[-/.](1[0-2]|0?[1-9])(?:[-/.](3[01]|[12]\d|0?[1-9]))?)?")


def _normalise(raw: str) -> str:
    match = _ISO.search(raw or "")
    if not match:
        return ""
    parts = re.split(r"[-/.]", match.group(0))
    year = int(parts[0])
    if year > now().year + 1:
        return ""
    return "-".join([parts[0], *[p.zfill(2) for p in parts[1:]]])


def published_date(html: str) -> str:
    """The publication date a page declares about itself, as YYYY[-MM[-DD]], or ""."""
    head = (html or "")[:400_000]
    for tag in _META_DATE.finditer(head):
        content = _CONTENT.search(tag.group(0))
        if content and (value := _normalise(content.group(1))):
            return value
    for pattern in (_JSONLD_DATE, _TIME_TAG):
        match = pattern.search(head)
        if match and (value := _normalise(match.group(1))):
            return value
    return ""
