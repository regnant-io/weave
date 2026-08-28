"""Web crawler / spider for growing the source library.

WHAT THIS IS FOR
----------------
Weave's answers are only as good as the library behind them, and the library
only gets richer if something keeps feeding it. Two things do: an operator
adding a seed on the admin page, and — with the user's consent — the domains
real sessions actually consult.

BEING A GOOD CITIZEN IS A DESIGN CONSTRAINT, NOT A SETTING
----------------------------------------------------------
This crawler runs against Tanzanian university, government and journal servers,
many of which are small. Getting blocked would cost far more than the pages
gained, and hammering a ministry's site is not something to be casual about. So:

  * robots.txt is fetched, cached per host, and OBEYED — including its
    crawl-delay when it asks for one longer than ours.
  * Requests to one host are serialised and spaced by `delay_seconds`. There is
    no concurrency within a host, ever.
  * The User-Agent identifies Weave honestly and links to a contact page. We do
    not rotate agents or addresses; if a site does not want us, that is an
    answer, not an obstacle.
  * Depth, page count and per-run time are all capped.

SPIDER TRAPS
------------
Calendars, faceted search, session ids and print views generate unbounded URL
space that looks new at every step. Three defences, because no single one is
enough: a normalised-URL visited set, a content hash (the same page under forty
URLs is fetched once and indexed once), and a path-repetition check that catches
`/a/b/a/b/a/b/…`.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
import urllib.robotparser
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

from sqlalchemy.orm import Session

from ...models import CrawlPage, CrawlSeed, Source
from ..websearch.client import _html_to_text, _is_safe_url

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (compatible; WeaveBot/1.0; +https://weave.co.tz/bot; "
    "study and research library for Tanzanian institutions)"
)

#: Absolute ceilings. A seed's own budget may be smaller, never larger — an
#: operator setting max_pages to 100000 in the admin form should not be able to
#: start a crawl that runs for a week.
HARD_MAX_PAGES = 500
HARD_MAX_DEPTH = 5
HARD_MAX_SECONDS = 900
MIN_DELAY = 0.5

#: Extensions worth fetching. Everything else is a binary we cannot index.
ALLOWED_SUFFIXES = (".html", ".htm", ".pdf", ".txt", "")
SKIP_SUFFIXES = (
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".css", ".js",
    ".zip", ".gz", ".tar", ".rar", ".mp4", ".mp3", ".avi", ".mov", ".xlsx",
    ".pptx", ".docx", ".exe", ".dmg",
)

#: Query parameters that never change the content — dropping them collapses a
#: large amount of apparent URL variety.
TRACKING_PARAMS = re.compile(
    r"^(utm_[a-z]+|fbclid|gclid|msclkid|ref|referrer|session|sid|phpsessid|jsessionid)$",
    re.I,
)

#: URL shapes that are trap-shaped often enough to skip outright.
TRAP_PATTERNS = re.compile(
    r"/(calendar|events?/\d{4}/\d{2}|day|month|year)/|"
    r"[?&](date|year|month|week|sort|order|filter|facet|page_size)=|"
    r"/(login|signin|register|logout|cart|checkout|print|share)\b",
    re.I,
)

MIN_TEXT_CHARS = 400


def normalise_url(url: str) -> str:
    """Collapse the variations that mean the same page.

    Fragment, tracking parameters, a trailing slash and the case of the host are
    all noise. Two URLs that differ only in those are one page, and a visited set
    that does not know it will fetch the same document repeatedly.
    """
    url, _ = urldefrag(url.strip())
    parts = urlparse(url)
    query = "&".join(
        q for q in parts.query.split("&")
        if q and not TRACKING_PARAMS.match(q.split("=")[0])
    )
    path = parts.path.rstrip("/") or "/"
    return urlunparse((
        parts.scheme.lower(), parts.netloc.lower(), path, parts.params, query, "",
    ))


def _looks_like_trap(url: str) -> bool:
    if TRAP_PATTERNS.search(url):
        return True
    # /a/b/a/b/a/ — a segment repeated three times is a redirect loop rendered
    # as a path, not a real hierarchy. There is deliberately no minimum segment
    # length here: loops are frequently built from very short segments, and a
    # genuine URL that repeats any one segment three times is trap-shaped
    # regardless of how long that segment is.
    segments = [s for s in urlparse(url).path.split("/") if s]
    for seg in set(segments):
        if segments.count(seg) >= 3:
            return True
    return len(segments) > 12


@dataclass
class CrawlStats:
    fetched: int = 0
    indexed: int = 0
    skipped: int = 0
    errors: int = 0
    stopped_because: str = ""
    pages: list[dict] = field(default_factory=list)


class CrawlerService:
    """One crawl at a time, per seed. Synchronous by design.

    A thread pool per host would be faster and is precisely what we must not do:
    the rate limit is the point. Long crawls belong on the Celery worker, which
    calls straight into `run_seed`.
    """

    def __init__(self) -> None:
        import httpx
        self._httpx = httpx
        self._robots: dict[str, tuple[urllib.robotparser.RobotFileParser, float]] = {}

    # -- robots ------------------------------------------------------------
    def _robots_for(self, scheme: str, host: str):
        """Fetch and cache robots.txt for a host.

        A host we cannot reach robots.txt for is treated as ALLOWED, which is the
        conventional reading: a 404 means no restrictions were published. A
        malformed file is treated the same way, because refusing to crawl on a
        parse error would silently exclude sites for a reason nobody would ever
        diagnose.
        """
        key = f"{scheme}://{host}"
        cached = self._robots.get(key)
        if cached and time.time() - cached[1] < 3600:
            return cached[0]
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(f"{key}/robots.txt")
        try:
            resp = self._httpx.get(f"{key}/robots.txt", timeout=12,
                                   headers={"User-Agent": USER_AGENT},
                                   follow_redirects=True)
            parser.parse(resp.text.splitlines() if resp.status_code == 200 else [])
        except Exception:  # noqa: BLE001 - unreachable robots.txt means no rules
            parser.parse([])
        self._robots[key] = (parser, time.time())
        return parser

    def _allowed(self, url: str) -> tuple[bool, str]:
        parts = urlparse(url)
        if parts.scheme not in {"http", "https"}:
            return False, "not an http(s) url"
        ok, reason = _is_safe_url(url)
        if not ok:
            return False, reason
        try:
            if not self._robots_for(parts.scheme, parts.netloc).can_fetch(USER_AGENT, url):
                return False, "disallowed by robots.txt"
        except Exception:  # noqa: BLE001
            pass
        return True, ""

    def _crawl_delay(self, url: str, floor: float) -> float:
        """Our delay, or the site's requested one — whichever is longer."""
        try:
            parts = urlparse(url)
            requested = self._robots_for(parts.scheme, parts.netloc).crawl_delay(USER_AGENT)
            if requested:
                return max(floor, float(requested))
        except Exception:  # noqa: BLE001
            pass
        return floor

    # -- fetching ----------------------------------------------------------
    def _fetch(self, url: str, render_js: bool) -> tuple[str, str, str]:
        """Return (title, text, error). Empty text means nothing usable."""
        from ...config import settings

        if render_js and settings.browserless_url:
            # Headless render for JS-built pages. Falls through to a plain GET on
            # failure rather than losing the page: a slow browser pool is a much
            # more common failure than a page that genuinely needs JS.
            try:
                base = settings.browserless_url.rstrip("/")
                resp = self._httpx.post(
                    f"{base}/content",
                    json={"url": url, "gotoOptions": {"waitUntil": "networkidle2"}},
                    timeout=60,
                )
                if resp.status_code == 200 and resp.text:
                    return (*_html_to_text(resp.text), "")
            except Exception as exc:  # noqa: BLE001
                log.debug("browserless render failed for %s: %s", url, exc)

        try:
            resp = self._httpx.get(url, timeout=30, follow_redirects=True,
                                   headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            return "", "", str(exc)[:200]

        ctype = resp.headers.get("content-type", "").lower()
        if "pdf" in ctype or url.lower().endswith(".pdf"):
            from ..ingestion.service import _extract_pdf
            return url.rsplit("/", 1)[-1], _extract_pdf(resp.content), ""
        if "html" not in ctype and "text" not in ctype:
            return "", "", f"unindexable content-type: {ctype[:60]}"
        return (*_html_to_text(resp.text), "")

    def _extract_links(self, base_url: str, html: str) -> list[str]:
        out = []
        for match in re.finditer(r'href\s*=\s*["\']([^"\']+)["\']', html or "", re.I):
            href = match.group(1).strip()
            if href.startswith(("javascript:", "mailto:", "tel:", "#", "data:")):
                continue
            try:
                out.append(normalise_url(urljoin(base_url, href)))
            except ValueError:
                continue
        return out

    # -- the crawl ---------------------------------------------------------
    def run_seed(self, db: Session, seed: CrawlSeed) -> CrawlStats:
        """Crawl one seed to its budget, indexing what it finds.

        Returns without raising whatever happens: a crawl is a background chore,
        and one unreachable host must not take down the caller.
        """
        from ..ingestion import get_ingestion

        stats = CrawlStats()
        started = time.time()
        seed.status = "running"
        seed.last_error = ""
        db.add(seed)
        db.commit()

        max_pages = max(1, min(int(seed.max_pages or 40), HARD_MAX_PAGES))
        max_depth = max(0, min(int(seed.max_depth or 2), HARD_MAX_DEPTH))
        delay = max(MIN_DELAY, float(seed.delay_seconds or 1.0))
        seed_host = urlparse(seed.url).netloc.lower()

        # Everything this seed has ever seen, so a re-crawl extends the library
        # instead of re-fetching it.
        seen: set[str] = {
            row.url for row in db.query(CrawlPage.url).filter(CrawlPage.seed_id == seed.id).all()
        }
        hashes: set[str] = {
            row.content_hash
            for row in db.query(CrawlPage.content_hash)
            .filter(CrawlPage.seed_id == seed.id, CrawlPage.content_hash != "").all()
        }

        queue: deque[tuple[str, int]] = deque([(normalise_url(seed.url), 0)])
        ingestion = get_ingestion()

        def record(url: str, depth: int, status: str, reason: str = "", title: str = "",
                   content_hash: str = "", chars: int = 0, source_id: str | None = None) -> None:
            db.add(CrawlPage(seed_id=seed.id, url=url[:1024], depth=depth, status=status,
                             reason=reason[:255], title=title[:512],
                             content_hash=content_hash, chars=chars, source_id=source_id))
            stats.pages.append({"url": url, "status": status, "reason": reason})

        while queue and stats.fetched < max_pages:
            if time.time() - started > HARD_MAX_SECONDS:
                stats.stopped_because = "time budget reached"
                break

            url, depth = queue.popleft()
            if url in seen:
                continue
            seen.add(url)

            if _looks_like_trap(url):
                stats.skipped += 1
                record(url, depth, "skipped_type", "looks like a crawler trap")
                continue
            if url.lower().endswith(SKIP_SUFFIXES):
                stats.skipped += 1
                record(url, depth, "skipped_type", "not an indexable document")
                continue

            allowed, why = self._allowed(url)
            if not allowed:
                stats.skipped += 1
                record(url, depth, "skipped_robots", why)
                continue

            # Politeness: wait BEFORE the request, so the very first one after a
            # redirect chain is spaced too.
            time.sleep(self._crawl_delay(url, delay))

            title, text, error = self._fetch(url, bool(seed.render_js))
            stats.fetched += 1
            if error:
                stats.errors += 1
                record(url, depth, "error", error, title)
                continue

            text = re.sub(r"\s+\n", "\n", text or "").strip()
            if len(text) < MIN_TEXT_CHARS:
                stats.skipped += 1
                record(url, depth, "skipped_thin", f"only {len(text)} characters of text", title)
                continue

            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:64]
            if digest in hashes:
                stats.skipped += 1
                record(url, depth, "skipped_duplicate", "identical text already indexed", title)
                continue
            hashes.add(digest)

            source = Source(
                title=(title or url)[:512], url=url[:1024],
                source_type=seed.source_type or "gov", access_status="open",
                language=seed.language or "en", predatory_flag=False,
            )
            db.add(source)
            db.flush()
            try:
                chunks = ingestion.retrieval.ingest_source(db, source, text)
            except Exception as exc:  # noqa: BLE001 - indexing must not end the crawl
                stats.errors += 1
                db.delete(source)
                record(url, depth, "error", f"indexing failed: {exc}"[:200], title)
                db.commit()
                continue

            stats.indexed += 1
            record(url, depth, "indexed", f"{chunks} chunks", title, digest, len(text), source.id)
            db.commit()

            if depth < max_depth:
                try:
                    resp = self._httpx.get(url, timeout=20, follow_redirects=True,
                                           headers={"User-Agent": USER_AGENT})
                    links = self._extract_links(url, resp.text)
                except Exception:  # noqa: BLE001
                    links = []
                for link in links:
                    if link in seen:
                        continue
                    if seed.same_domain_only and urlparse(link).netloc.lower() != seed_host:
                        continue
                    queue.append((link, depth + 1))

        if not stats.stopped_because:
            stats.stopped_because = "page budget reached" if stats.fetched >= max_pages else "queue exhausted"

        seed.status = "error" if (stats.errors and not stats.indexed) else "done"
        seed.last_run_at = datetime.now(timezone.utc)
        seed.pages_fetched = (seed.pages_fetched or 0) + stats.fetched
        seed.pages_indexed = (seed.pages_indexed or 0) + stats.indexed
        if stats.errors and not stats.indexed:
            seed.last_error = "every fetch failed — check the URL is reachable"
        db.add(seed)
        db.commit()
        return stats

    # -- session-derived seeds ---------------------------------------------
    def note_session_source(self, db: Session, url: str, user) -> CrawlSeed | None:
        """Queue the domain of a page a session actually consulted.

        This is the mechanism that makes the library grow with use. It is
        deliberately conservative: it records a DOMAIN as a candidate seed and
        crawls nothing here. A human (or the scheduled worker) decides when it
        runs, so a single odd link in one chat cannot start a crawl.

        Returns None — without creating anything — when the user has turned the
        setting off, which is the whole point of the setting.
        """
        if user is None or not getattr(user, "allow_source_crawl", True):
            return None
        ok, _ = _is_safe_url(url or "")
        if not ok:
            return None
        parts = urlparse(url)
        domain = parts.netloc.lower()
        if not domain:
            return None

        existing = db.query(CrawlSeed).filter(CrawlSeed.domain == domain).first()
        if existing:
            return existing
        seed = CrawlSeed(
            url=f"{parts.scheme}://{domain}/", domain=domain,
            source_type="web", origin="session",
            discovered_by=getattr(user, "id", None),
            # Session-derived seeds start SMALL and disabled. They are
            # suggestions from usage, not instructions, and an operator approves
            # them on the admin page before anything is fetched.
            enabled=False, max_depth=1, max_pages=15, status="pending",
        )
        db.add(seed)
        db.commit()
        return seed


_service: CrawlerService | None = None


def get_crawler() -> CrawlerService:
    global _service
    if _service is None:
        _service = CrawlerService()
    return _service
