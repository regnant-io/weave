"""Web search without a search daemon, for the desktop build.

A server deployment runs SearXNG next to the backend. A desktop installation
cannot: there is no container runtime to put it in. The first desktop search
path used Bing's RSS endpoint, which answers anonymous clients with results
unrelated to the query. "thinking machines lab" came back as "How to get help
in Windows". The model then honestly reported that nothing could be found,
which was worse than having no search at all.

This module queries public HTML search pages that need no key, parses them
with small pure functions (tested against captured fixtures), and falls
through a provider chain:

  1. DuckDuckGo HTML   (html.duckduckgo.com/html)
  2. DuckDuckGo Lite   (lite.duckduckgo.com/lite): different markup, and it
                       often still answers when (1) is rate limited
  3. Bing RSS          last resort, kept only for results that actually share
                       terms with the query

A provider that rate-limits us is benched for a short cool-down instead of
being retried on every call. Image search goes to the Wikimedia Commons API,
which is keyless, stable and licensed for reuse.
"""
from __future__ import annotations

import html as html_entities
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

log = logging.getLogger("weave.websearch")

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")
_COMMONS_UA = "Weave/1.0 (local research assistant; desktop)"

#: How long a provider that answered with a challenge / rate limit is skipped.
_COOLDOWN_SECONDS = 90.0


@dataclass
class Hit:
    title: str
    url: str
    snippet: str
    engine: str


# --------------------------------------------------------------------------- #
#  Parsers (pure)                                                              #
# --------------------------------------------------------------------------- #
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _text(fragment: str) -> str:
    return _WS_RE.sub(" ", html_entities.unescape(_TAG_RE.sub(" ", fragment or ""))).strip()


def decode_ddg_href(href: str) -> str:
    """Resolve DuckDuckGo's redirect wrapper to the real target URL.

    Organic results are `//duckduckgo.com/l/?uddg=<encoded target>&rut=...`.
    Ads go through `/y.js` and carry no `uddg`, so they come back as "" and are
    dropped. Direct http(s) links pass through unchanged.
    """
    raw = html_entities.unescape(href or "").strip()
    if raw.startswith("//"):
        raw = "https:" + raw
    try:
        parsed = urlparse(raw)
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    if host.endswith("duckduckgo.com"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        target = unquote(target) if target else ""
        return target if target.startswith(("http://", "https://")) else ""
    return raw if parsed.scheme in {"http", "https"} else ""


_DDG_RESULT_RE = re.compile(
    r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_DDG_SNIPPET_RE = re.compile(
    r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', re.S)


def parse_ddg_html(page: str) -> list[Hit]:
    """Organic results from html.duckduckgo.com, ads excluded."""
    hits: list[Hit] = []
    # Split into result blocks so a snippet is never paired with the wrong link.
    blocks = re.split(r'<div[^>]+class="[^"]*\bresult\b', page or "")
    for block in blocks[1:]:
        head = block[:200]
        if "result--ad" in head:
            continue
        link = _DDG_RESULT_RE.search(block)
        if not link:
            continue
        url = decode_ddg_href(link.group(1))
        if not url:
            continue
        snippet = _DDG_SNIPPET_RE.search(block)
        hits.append(Hit(title=_text(link.group(2))[:300], url=url,
                        snippet=_text(snippet.group(1))[:500] if snippet else "",
                        engine="duckduckgo"))
    return _dedupe(hits)


_LITE_LINK_RE = re.compile(
    r"""<a[^>]*href=["']([^"']+)["'][^>]*class=['"]result-link['"][^>]*>(.*?)</a>"""
    r"""|<a[^>]*class=['"]result-link['"][^>]*href=["']([^"']+)["'][^>]*>(.*?)</a>""",
    re.S)
_LITE_SNIPPET_RE = re.compile(r"<td[^>]*class=['\"]result-snippet['\"][^>]*>(.*?)</td>", re.S)


def parse_ddg_lite(page: str) -> list[Hit]:
    """Results from lite.duckduckgo.com: a table, links and snippets in order."""
    links = []
    for match in _LITE_LINK_RE.finditer(page or ""):
        href = match.group(1) or match.group(3) or ""
        title = match.group(2) or match.group(4) or ""
        links.append((decode_ddg_href(href), _text(title)))
    snippets = [_text(s) for s in _LITE_SNIPPET_RE.findall(page or "")]
    hits = []
    for index, (url, title) in enumerate(links):
        if not url:
            continue
        hits.append(Hit(title=title[:300], url=url,
                        snippet=(snippets[index] if index < len(snippets) else "")[:500],
                        engine="duckduckgo-lite"))
    return _dedupe(hits)


def parse_bing_rss(payload: bytes) -> list[Hit]:
    root = ET.fromstring(payload[:1_000_000])
    hits = []
    for item in root.findall("./channel/item"):
        url = (item.findtext("link") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        hits.append(Hit(
            title=_text(item.findtext("title") or "")[:300], url=url,
            snippet=_text(item.findtext("description") or "")[:500], engine="bing-rss",
        ))
    return _dedupe(hits)


_STOP = {"the", "a", "an", "of", "and", "or", "in", "on", "for", "to", "is", "are",
         "what", "how", "why", "who", "with", "by", "from", "about", "recent", "latest",
         "na", "ya", "wa", "kwa", "za", "la", "cha", "vya", "ni"}


def _terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", (text or "").lower()) if w not in _STOP}


def relevant(hits: list[Hit], query: str) -> list[Hit]:
    """Keep hits sharing at least one meaningful term with the query.

    Only applied to the Bing fallback, the provider known to answer with
    unrelated results. A query with no usable terms keeps everything.
    """
    wanted = _terms(query)
    if not wanted:
        return hits
    return [h for h in hits if wanted & _terms(f"{h.title} {h.snippet} {h.url}")]


def _dedupe(hits: list[Hit]) -> list[Hit]:
    seen: set[str] = set()
    out = []
    for hit in hits:
        key = hit.url.split("#", 1)[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append(hit)
    return out


def _looks_blocked(status: int, body: str) -> bool:
    """A challenge page, not an empty result set."""
    if status in {202, 403, 418, 429}:
        return True
    low = (body or "")[:6000].lower()
    return "anomaly-modal" in low or "please complete the following challenge" in low


# --------------------------------------------------------------------------- #
#  Provider chain                                                              #
# --------------------------------------------------------------------------- #
class SearchOutage(RuntimeError):
    """Every provider failed. Distinct from "the web has nothing on this"."""


class KeylessSearch:
    def __init__(self, httpx_module, timeout: float = 15.0) -> None:
        self._httpx = httpx_module
        self._timeout = timeout
        self._benched: dict[str, float] = {}
        self._lock = threading.Lock()

    # -- cool-down bookkeeping -------------------------------------------------
    def _available(self, name: str) -> bool:
        with self._lock:
            until = self._benched.get(name, 0.0)
        return time.monotonic() >= until

    def _bench(self, name: str) -> None:
        with self._lock:
            self._benched[name] = time.monotonic() + _COOLDOWN_SECONDS

    def _get(self, url: str, params: dict, headers: dict | None = None):
        return self._httpx.get(
            url, params=params, timeout=self._timeout, follow_redirects=True,
            headers={"User-Agent": _UA, "Accept-Language": "en;q=0.9,sw;q=0.8",
                     **(headers or {})},
        )

    # -- providers ---------------------------------------------------------------
    def _ddg_html(self, query: str) -> list[Hit]:
        r = self._get("https://html.duckduckgo.com/html/", {"q": query})
        if _looks_blocked(r.status_code, r.text):
            raise PermissionError(f"challenge (HTTP {r.status_code})")
        r.raise_for_status()
        return parse_ddg_html(r.text)

    def _ddg_lite(self, query: str) -> list[Hit]:
        r = self._get("https://lite.duckduckgo.com/lite/", {"q": query})
        if _looks_blocked(r.status_code, r.text):
            raise PermissionError(f"challenge (HTTP {r.status_code})")
        r.raise_for_status()
        return parse_ddg_lite(r.text)

    def _bing_rss(self, query: str) -> list[Hit]:
        r = self._get("https://www.bing.com/search", {"q": query, "format": "rss"})
        r.raise_for_status()
        return relevant(parse_bing_rss(r.content), query)

    def search(self, query: str, limit: int) -> list[Hit]:
        """First provider with results wins. Raises SearchOutage if all fail."""
        query = (query or "").strip()[:500]
        if not query:
            return []
        providers = (("ddg_html", self._ddg_html), ("ddg_lite", self._ddg_lite),
                     ("bing_rss", self._bing_rss))
        failures: list[str] = []
        answered = False
        for name, provider in providers:
            if not self._available(name):
                failures.append(f"{name}: cooling down")
                continue
            try:
                hits = provider(query)
            except PermissionError as exc:
                self._bench(name)
                failures.append(f"{name}: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001 - try the next provider
                failures.append(f"{name}: {type(exc).__name__}")
                continue
            answered = True
            if hits:
                return hits[: max(1, limit)]
        if not answered:
            log.warning("keyless web search unavailable: %s", "; ".join(failures))
            raise SearchOutage("; ".join(failures) or "no provider answered")
        return []

    def images(self, query: str, limit: int) -> list[dict]:
        """Freely licensed images from Wikimedia Commons."""
        query = (query or "").strip()[:300]
        if not query:
            return []
        try:
            r = self._httpx.get(
                "https://commons.wikimedia.org/w/api.php",
                params={
                    "action": "query", "format": "json", "generator": "search",
                    "gsrnamespace": 6, "gsrsearch": f"{query} filetype:bitmap",
                    "gsrlimit": max(1, min(limit * 2, 20)), "prop": "imageinfo",
                    "iiprop": "url|mime", "iiurlwidth": 640,
                },
                timeout=self._timeout,
                headers={"User-Agent": _COMMONS_UA},
            )
            r.raise_for_status()
            pages = (r.json().get("query") or {}).get("pages") or {}
        except Exception as exc:  # noqa: BLE001 - images are decoration
            log.debug("commons image search failed: %s", exc)
            return []
        ordered = sorted(pages.values(), key=lambda p: p.get("index", 0))
        out = []
        for page in ordered:
            info = (page.get("imageinfo") or [{}])[0]
            if not str(info.get("mime", "")).startswith("image/"):
                continue
            url = info.get("thumburl") or info.get("url")
            if not url or not url.startswith("https://"):
                continue
            title = str(page.get("title") or "").removeprefix("File:")
            title = re.sub(r"\.(jpe?g|png|gif|webp|tiff?)$", "", title, flags=re.I)
            out.append({"url": url, "title": title[:160], "source": "Wikimedia Commons"})
            if len(out) >= limit:
                break
        return out
