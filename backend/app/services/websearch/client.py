"""Deep web search client.

Backed by two self-hosted services (both optional; graceful-degrades if absent):

  * SearXNG  — privacy metasearch, aggregates many engines, JSON API.
  * Browserless / Playwright — headless-Chrome pool for JS-rendered fetches.

Security (this is a hostile-input surface — architecture Design Principle 4):
  * SSRF guard: refuse private / loopback / link-local / cloud-metadata targets.
  * Content fetched from the web is DATA, never instructions — the orchestrator
    must never execute directives found in fetched pages.
  * Fetches are size-capped and time-bounded.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from ...config import settings

# Blocked destinations for SSRF protection.
_BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}
_METADATA_IPS = {"169.254.169.254", "100.100.100.200"}  # AWS/GCP/Azure, Alibaba


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    engine: str = ""


@dataclass
class FetchedPage:
    url: str
    title: str
    text: str
    ok: bool
    error: str = ""


def _is_safe_url(url: str) -> tuple[bool, str]:
    try:
        p = urlparse(url)
    except ValueError:
        return False, "unparseable url"
    if p.scheme not in {"http", "https"}:
        return False, f"scheme {p.scheme!r} not allowed"
    host = p.hostname or ""
    if host.lower() in _BLOCKED_HOSTS:
        return False, "blocked host"
    # resolve and reject private / loopback / link-local / reserved ranges
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False, "dns resolution failed"
    for info in infos:
        ip_str = info[4][0]
        if ip_str in _METADATA_IPS:
            return False, "cloud metadata endpoint blocked"
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False, f"non-public address {ip_str} blocked"
    return True, ""


def _html_to_text(html: str) -> tuple[str, str]:
    """Extract (title, clean text). Uses trafilatura if available, else a
    dependency-free readability-lite pass."""
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()[:300]

    try:
        import trafilatura  # optional, better extraction
        extracted = trafilatura.extract(html, include_comments=False, include_tables=True)
        if extracted:
            return title, extracted.strip()
    except Exception:  # noqa: BLE001 - fall through to the basic path
        pass

    # basic fallback: strip scripts/styles/tags
    cleaned = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"&nbsp;", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return title, cleaned


class WebSearchClient:
    def __init__(self) -> None:
        import httpx
        self._httpx = httpx

    @property
    def enabled(self) -> bool:
        return bool(settings.searxng_url)

    def search(self, query: str, max_results: int | None = None,
               language: str = "en") -> list[SearchResult]:
        if not settings.searxng_url:
            return []
        n = max_results or settings.websearch_max_results
        httpx = self._httpx
        try:
            r = httpx.get(
                settings.searxng_url.rstrip("/") + "/search",
                params={"q": query, "format": "json", "language": language,
                        "safesearch": 1},
                timeout=settings.websearch_fetch_timeout,
                headers={"User-Agent": "weave-research/1.0"},
            )
            r.raise_for_status()
            data = r.json()
        except Exception:  # noqa: BLE001 - service down -> no results (caller degrades)
            return []
        results = []
        for item in data.get("results", [])[: n]:
            results.append(SearchResult(
                title=item.get("title", "")[:300],
                url=item.get("url", ""),
                snippet=(item.get("content") or "")[:500],
                engine=item.get("engine", ""),
            ))
        return results

    def search_images(self, query: str, n: int = 4, language: str = "en") -> list[dict]:
        """Top image results (SearXNG images category) for the in-chat image grid."""
        if not settings.searxng_url:
            return []
        httpx = self._httpx
        try:
            r = httpx.get(
                settings.searxng_url.rstrip("/") + "/search",
                params={"q": query, "format": "json", "categories": "images",
                        "language": language, "safesearch": 1},
                timeout=settings.websearch_fetch_timeout,
                headers={"User-Agent": "weave-research/1.0"},
            )
            r.raise_for_status()
            data = r.json()
        except Exception:  # noqa: BLE001
            return []
        out = []
        for item in data.get("results", []):
            url = item.get("img_src") or item.get("thumbnail_src") or item.get("url")
            if not url or not url.startswith("http"):
                continue
            ok, _ = _is_safe_url(url)
            if not ok:
                continue
            out.append({"url": url, "title": (item.get("title") or "")[:160],
                        "source": item.get("source") or item.get("engine") or ""})
            if len(out) >= n:
                break
        return out

    def fetch(self, url: str) -> FetchedPage:
        ok, reason = _is_safe_url(url)
        if not ok:
            return FetchedPage(url=url, title="", text="", ok=False, error=reason)

        httpx = self._httpx
        # Direct GET — fast and reliable. (Browserless waits for network-idle on
        # ad/tracker-heavy pages that never idle, causing 408s, so it is NOT used
        # for research fetches; it stays reserved for the render/screenshot path.)
        try:
            resp = httpx.get(
                url, timeout=settings.websearch_fetch_timeout, follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; weave-research/1.0)"},
            )
            resp.raise_for_status()
            html = resp.text
        except Exception as exc:  # noqa: BLE001
            return FetchedPage(url=url, title="", text="", ok=False, error=str(exc)[:200])

        html = html[: settings.research_max_fetch_bytes]
        title, text = _html_to_text(html)
        return FetchedPage(url=url, title=title, text=text, ok=True)

    def _fetch_via_browserless(self, url: str) -> str:
        httpx = self._httpx
        base = settings.browserless_url.rstrip("/")
        # Browserless /content returns the fully-rendered HTML.
        r = httpx.post(
            f"{base}/content",
            json={"url": url, "gotoOptions": {"waitUntil": "networkidle2"}},
            timeout=settings.websearch_fetch_timeout + 10,
        )
        r.raise_for_status()
        return r.text


_client: WebSearchClient | None = None


def get_web_search() -> WebSearchClient:
    global _client
    if _client is None:
        _client = WebSearchClient()
    return _client
