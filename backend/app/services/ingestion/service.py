"""Ingestion pipeline (architecture §7.2).

  source URL -> fetch (SSRF-guarded) -> extract (HTML via trafilatura / PDF via
  pypdf) -> chunk + embed + index (delegated to the Retrieval Service).

Connectors are just (source_type, base) hints; the generic URL/PDF path handles
UDSM/NBS/COSTECH open documents. Scheduling is via Celery beat / the admin
trigger; this module is transport-agnostic.
"""
from __future__ import annotations

import io
import re

from sqlalchemy.orm import Session

from ...models import Source, SourceChunk
from ...storage import storage
from ..retrieval import get_retrieval_service
from ..websearch.client import _is_safe_url, _html_to_text


def _extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:  # noqa: BLE001
        return ""


class IngestionService:
    def __init__(self) -> None:
        import httpx
        self._httpx = httpx
        self.retrieval = get_retrieval_service()

    def fetch(self, url: str) -> tuple[str, str]:
        """Return (title, text) for a URL. Empty text on failure."""
        ok, _ = _is_safe_url(url)
        if not ok:
            return "", ""
        try:
            r = self._httpx.get(url, timeout=30, follow_redirects=True,
                                headers={"User-Agent": "Mozilla/5.0 (compatible; weave-ingest/1.0)"})
            r.raise_for_status()
        except Exception:  # noqa: BLE001
            return "", ""
        ctype = r.headers.get("content-type", "")
        if "pdf" in ctype or url.lower().endswith(".pdf"):
            text = _extract_pdf(r.content)
            title = url.rsplit("/", 1)[-1]
            return title, text
        title, text = _html_to_text(r.text)
        return title, text

    def ingest(self, db: Session, source: Source) -> int:
        """(Re)ingest a Source from its URL. Returns chunk count. Idempotent:
        clears prior chunks for the source first."""
        if not source.url:
            return 0
        title, text = self.fetch(source.url)
        text = re.sub(r"\s+\n", "\n", text or "").strip()
        if len(text) < 120:
            return 0
        # store raw (versioned) for audit + reprocessing
        try:
            storage.put_bytes(f"ingest/{source.id}.txt", text.encode("utf-8"))
        except Exception:  # noqa: BLE001
            pass
        # clear old chunks then re-index
        db.query(SourceChunk).filter(SourceChunk.source_id == source.id).delete()
        db.commit()
        if title and not source.title:
            source.title = title[:512]
            db.add(source)
            db.commit()
        return self.retrieval.ingest_source(db, source, text)

    def ingest_url(self, db: Session, url: str, source_type: str = "gov",
                   access_status: str = "open", language: str = "en",
                   title: str | None = None) -> Source:
        """Create a Source for a URL and ingest it now."""
        src = Source(title=title or url, url=url, source_type=source_type,
                     access_status=access_status, language=language, predatory_flag=False)
        db.add(src)
        db.flush()
        self.ingest(db, src)
        db.commit()
        db.refresh(src)
        return src


_service: IngestionService | None = None


def get_ingestion() -> IngestionService:
    global _service
    if _service is None:
        _service = IngestionService()
    return _service
