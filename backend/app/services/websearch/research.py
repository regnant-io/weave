"""Iterative deep-research loop.

  search (SearXNG) -> deep-read top pages (Browserless/direct, SSRF-safe)
    -> extract clean text -> chunk into passages with provenance
    -> (optional) another round to fill gaps

Returns passages shaped like the Retrieval Service's, so the orchestrator's
grounding + citation machinery treats web results and local sources uniformly.
Progress is streamed via `emit(event, data)` for the SSE UI.
"""
from __future__ import annotations

import re
from typing import Callable

from ...config import settings
from .client import WebSearchClient


# Neutralise obvious prompt-injection lines embedded in crawled pages before the
# content ever reaches the model. Defence-in-depth atop the system-prompt rule.
_INJECTION_RE = re.compile(
    r"(?im)^.*(ignore (all |the )?(previous|above|prior) (instructions|prompts)|"
    r"disregard (the )?(system|previous)|you are now|new instructions:|"
    r"system prompt:|assistant:|\bDAN\b|jailbreak).*$")


def _sanitize(text: str) -> str:
    return _INJECTION_RE.sub("[removed]", text or "")


def _chunk(text: str, title: str, url: str, target_words: int = 140, max_chunks: int = 3) -> list[dict]:
    text = _sanitize(text)
    words = text.split()
    chunks = []
    for i in range(0, min(len(words), target_words * max_chunks), target_words):
        content = " ".join(words[i:i + target_words]).strip()
        if len(content) < 40:
            continue
        chunks.append({
            "source_id": url, "chunk_id": f"{url}#{i}", "title": title or url,
            "url": url, "source_type": "web", "access_status": "open",
            "language": "mixed", "predatory_flag": False, "content": content,
            "score": 0.0,
        })
    return chunks


def _refine(query: str, seen_titles: list[str], round_idx: int) -> str:
    """Naive query refinement for later rounds: bias toward specifics/recency."""
    if round_idx == 0:
        return query
    hint = "statistics data report" if round_idx == 1 else "study evidence"
    return f"{query} {hint}"


def deep_research(
    client: WebSearchClient,
    query: str,
    *,
    rounds: int | None = None,
    max_pages: int | None = None,
    language: str = "en",
    emit: Callable[[str, dict], None] | None = None,
) -> dict:
    """Run the loop; return {passages, pages_read, queries, available}."""
    def _emit(ev: str, data: dict) -> None:
        if emit:
            emit(ev, data)

    if not client.enabled:
        _emit("research", {"status": "unavailable",
                           "message": "web search service (SearXNG) not configured"})
        return {"passages": [], "pages_read": 0, "queries": [], "available": False}

    rounds = rounds or settings.research_max_rounds
    max_pages = max_pages or settings.websearch_max_pages

    passages: list[dict] = []
    seen_urls: set[str] = set()
    seen_titles: list[str] = []
    queries: list[str] = []

    # top images for the in-chat grid (emitted once by the orchestrator)
    images = client.search_images(query, n=4, language=language)

    for r in range(rounds):
        q = _refine(query, seen_titles, r)
        queries.append(q)
        _emit("searching", {"round": r + 1, "query": q})
        results = client.search(q, language=language)
        _emit("search_results", {"round": r + 1, "count": len(results),
                                 "results": [{"title": x.title, "url": x.url} for x in results[:8]]})

        fresh = [x for x in results if x.url and x.url not in seen_urls][:max_pages]
        if not fresh:
            continue

        for res in fresh:
            seen_urls.add(res.url)
            _emit("fetching", {"url": res.url, "title": res.title})
            page = client.fetch(res.url)
            if not page.ok or len(page.text) < 120:
                _emit("fetch_skipped", {"url": res.url, "reason": page.error or "too little text"})
                continue
            seen_titles.append(page.title or res.title)
            chunks = _chunk(page.text, page.title or res.title, res.url)
            passages.extend(chunks)
            _emit("extracted", {"url": res.url, "chunks": len(chunks),
                                "chars": len(page.text)})

        # crude stop: enough material gathered
        if len(passages) >= max_pages * 3:
            break

    _emit("research", {"status": "done", "pages_read": len(seen_urls),
                       "passages": len(passages)})
    return {"passages": passages, "pages_read": len(seen_urls),
            "queries": queries, "available": True, "images": images}
