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
from typing import Any
from urllib.parse import urljoin, urlparse

from ...config import settings

# Blocked destinations for SSRF protection.
_BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}
_METADATA_IPS = {"169.254.169.254", "100.100.100.200"}  # AWS/GCP/Azure, Alibaba
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_MAX_REDIRECTS = 5


@dataclass
class _BufferedResponse:
    """Small response facade containing only a size-bounded response body."""

    status_code: int
    headers: Any
    content: bytes

    @property
    def text(self) -> str:
        ctype = str(self.headers.get("content-type", ""))
        match = re.search(r"charset=([^;\s]+)", ctype, re.I)
        encoding = (match.group(1).strip("\"'") if match else "utf-8")
        try:
            return self.content.decode(encoding, "replace")
        except LookupError:
            return self.content.decode("utf-8", "replace")

    def raise_for_status(self) -> None:
        if self.status_code >= 300:
            raise RuntimeError(f"upstream returned HTTP {self.status_code}")


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


def _safe_get(httpx_module, url: str, *, timeout, headers: dict | None = None,
              max_bytes: int | None = None):
    """GET while validating every redirect target against the SSRF policy.

    Validating only the first URL is insufficient: a public endpoint may reply
    with ``Location: http://127.0.0.1/...`` and an automatic redirect client
    will then cross the trust boundary on our behalf.
    """
    current = url
    byte_limit = max(1, int(max_bytes or settings.research_max_fetch_bytes))
    for hop in range(_MAX_REDIRECTS + 1):
        ok, reason = _is_safe_url(current)
        if not ok:
            raise ValueError(f"unsafe URL: {reason}")
        # `httpx.get()` buffers the complete body before returning, which makes
        # slicing it afterwards a cosmetic limit. Stream and stop while bytes
        # arrive so a chunked response or decompression bomb cannot consume
        # unbounded process memory.
        stream = getattr(httpx_module, "stream", None)
        if stream is None:  # tiny compatibility path for deterministic test fakes
            response = httpx_module.get(
                current, timeout=timeout, follow_redirects=False, headers=headers,
            )
            if response.status_code not in _REDIRECT_STATUSES:
                body = bytes(getattr(response, "content", b""))
                if len(body) > byte_limit:
                    raise ValueError(f"response exceeds {byte_limit} byte limit")
                return response
            location = response.headers.get("location")
        else:
            with stream(
                "GET", current, timeout=timeout, follow_redirects=False, headers=headers,
            ) as response:
                if response.status_code in _REDIRECT_STATUSES:
                    location = response.headers.get("location")
                else:
                    declared = response.headers.get("content-length")
                    if declared:
                        try:
                            if int(declared) > byte_limit:
                                raise ValueError(f"response exceeds {byte_limit} byte limit")
                        except ValueError as exc:
                            if "exceeds" in str(exc):
                                raise
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > byte_limit:
                            raise ValueError(f"response exceeds {byte_limit} byte limit")
                    return _BufferedResponse(
                        status_code=response.status_code,
                        headers=response.headers,
                        content=bytes(body),
                    )
        if not location:
            return response
        if hop >= _MAX_REDIRECTS:
            raise ValueError("too many redirects")
        current = urljoin(current, location)
    raise ValueError("too many redirects")


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
            resp = _safe_get(
                httpx, url, timeout=settings.websearch_fetch_timeout,
                headers={"User-Agent": "Mozilla/5.0 (compatible; weave-research/1.0)"},
            )
            resp.raise_for_status()
            html = resp.text
        except Exception as exc:  # noqa: BLE001
            return FetchedPage(url=url, title="", text="", ok=False, error=str(exc)[:200])

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
