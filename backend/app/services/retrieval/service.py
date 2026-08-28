"""Retrieval Service (architecture section 7).

Hybrid search over Tanzanian academic sources:
  * dense: vector similarity (pgvector in prod; numpy/pure-python cosine here)
  * sparse: keyword/BM25 via SQLite FTS5 (Postgres tsvector in prod)
  * fusion: reciprocal-rank fusion (RRF) to merge the two rankings (7.3)

Also enforces, at the data layer (not left to the model):
  * access-status labels on every passage (open | paywalled) — 7.3
  * predatory-journal flags — 6.5 / 7.2
  * a language-aware pass so a Swahili query can surface English sources — 7.3
"""
from __future__ import annotations

import re

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from ...config import settings
from ...models import Source, SourceChunk
from .embeddings import cosine, embed_text, embed_texts

# A small BAKITA-style academic glossary used for the language-aware retrieval
# pass (architecture 7.3): expand the keyword query with the other language's
# term so a Swahili question still hits English-only reports. A real deployment
# injects the full BAKITA glossary here.
GLOSSARY: dict[str, str] = {
    "utafiti": "research", "takwimu": "statistics data", "elimu": "education",
    "afya": "health", "uchumi": "economy economic", "kilimo": "agriculture",
    "idadi": "population count", "ripoti": "report", "sampuli": "sample",
    "dhana": "hypothesis concept", "matokeo": "results findings",
    "shule": "school", "chuo": "university college", "sera": "policy",
    "research": "utafiti", "statistics": "takwimu", "education": "elimu",
    "health": "afya", "economy": "uchumi", "agriculture": "kilimo",
    "population": "idadi", "report": "ripoti", "policy": "sera",
}

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _chunk_text(text: str, target_words: int = 120) -> list[str]:
    """Section-aware-ish chunking to ~400-600 tokens (architecture 7.2)."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf: list[str] = []
    count = 0
    for para in paragraphs:
        words = para.split()
        if count + len(words) > target_words and buf:
            chunks.append(" ".join(buf))
            buf, count = [], 0
        buf.append(para)
        count += len(words)
    if buf:
        chunks.append(" ".join(buf))
    return chunks or [text.strip()]


class RetrievalService:
    # -- ingestion (architecture 7.2) ----------------------------------------

    def ingest_source(self, db: Session, source: Source, full_text: str) -> int:
        """Chunk, embed and index a source's text. Returns chunk count."""
        chunks = _chunk_text(full_text)
        embeddings = embed_texts(chunks)
        created = []
        for ordinal, (content, emb) in enumerate(zip(chunks, embeddings)):
            chunk = SourceChunk(source_id=source.id, ordinal=ordinal, content=content, embedding=emb)
            db.add(chunk)
            created.append(chunk)
        db.flush()  # assign ids (uuid defaults are Python-side, available now)

        # BM25 half: mirror into the FTS5 virtual table (SQLite dev path). Use the
        # session's own connection — opening a second write connection while the
        # session holds a write lock would deadlock SQLite ("database is locked").
        if settings.is_sqlite:
            for chunk in created:
                db.execute(
                    sql_text("INSERT INTO source_chunk_fts(chunk_id, content) VALUES (:c, :t)"),
                    {"c": chunk.id, "t": chunk.content},
                )
        db.commit()
        return len(created)

    # -- retrieval (architecture 7.3) ----------------------------------------

    def search(
        self,
        db: Session,
        query: str,
        language: str = "sw",
        top_k: int | None = None,
        source_types: list[str] | None = None,
    ) -> list[dict]:
        top_k = top_k or settings.retrieval_top_k

        dense_ranked = self._dense_search(db, query, source_types, limit=top_k * 4)
        sparse_ranked = self._sparse_search(db, query, limit=top_k * 4)

        fused = self._rrf_fuse(dense_ranked, sparse_ranked)
        chunk_ids = [cid for cid, _ in fused[: top_k]]
        if not chunk_ids:
            return []

        chunks = {c.id: c for c in db.query(SourceChunk).filter(SourceChunk.id.in_(chunk_ids)).all()}
        sources = {
            s.id: s
            for s in db.query(Source).filter(
                Source.id.in_({chunks[c].source_id for c in chunk_ids if c in chunks})
            ).all()
        }

        # Lexical-relevance gate: the fusion always returns *something*, so with a
        # low-signal embedding an off-topic query (e.g. a non-Tanzania subject)
        # would surface irrelevant local passages and pollute grounding. Require a
        # content-word overlap between the (glossary-expanded) query and the
        # passage. This also lets the orchestrator fall through to web research
        # when there's no confident local match.
        query_terms = set(self._expand_query_tokens(query))

        def _relevant(text: str) -> bool:
            if not query_terms:
                return True
            passage_terms = {t for t in _WORD_RE.findall(text.lower()) if len(t) > 3}
            return bool(query_terms & passage_terms)

        results = []
        score_by_id = dict(fused)
        for cid in chunk_ids:
            chunk = chunks.get(cid)
            if not chunk:
                continue
            src = sources.get(chunk.source_id)
            if src is None:
                continue
            if source_types and src.source_type not in source_types:
                continue
            if not _relevant(chunk.content):
                continue
            results.append({
                "source_id": src.id,
                "chunk_id": chunk.id,
                "title": src.title,
                "url": src.url,
                "source_type": src.source_type,
                "access_status": src.access_status,   # enforced at data layer (7.3)
                "language": src.language,
                "predatory_flag": src.predatory_flag,  # enforced at data layer (6.5)
                "content": chunk.content,
                "score": round(float(score_by_id.get(cid, 0.0)), 6),
            })
        return results

    # -- internals ------------------------------------------------------------

    def _dense_search(self, db: Session, query: str, source_types, limit: int) -> list[tuple[str, float]]:
        qvec = embed_text(query)
        q = db.query(SourceChunk)
        rows = q.all()
        scored = []
        allowed_sources = None
        if source_types:
            allowed_sources = {
                s.id for s in db.query(Source.id).filter(Source.source_type.in_(source_types)).all()
            }
        for chunk in rows:
            if allowed_sources is not None and chunk.source_id not in allowed_sources:
                continue
            if not chunk.embedding:
                continue
            scored.append((chunk.id, cosine(qvec, chunk.embedding)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def _sparse_search(self, db: Session, query: str, limit: int) -> list[tuple[str, float]]:
        if not settings.is_sqlite:  # pragma: no cover - Postgres tsvector path
            return self._sparse_search_pg(db, query, limit)

        tokens = self._expand_query_tokens(query)
        if not tokens:
            return []
        match_expr = " OR ".join(f'"{t}"' for t in tokens)
        rows = db.execute(
            sql_text(
                "SELECT chunk_id, bm25(source_chunk_fts) AS rank "
                "FROM source_chunk_fts WHERE source_chunk_fts MATCH :q "
                "ORDER BY rank LIMIT :n"
            ),
            {"q": match_expr, "n": limit},
        ).fetchall()
        # bm25() returns lower = better; convert to a descending score list
        return [(r[0], -float(r[1])) for r in rows]

    def _sparse_search_pg(self, db: Session, query: str, limit: int):  # pragma: no cover
        tokens = self._expand_query_tokens(query)
        tsquery = " | ".join(tokens)
        rows = db.execute(
            sql_text(
                "SELECT id, ts_rank(to_tsvector('simple', content), to_tsquery('simple', :q)) AS rank "
                "FROM source_chunks WHERE to_tsvector('simple', content) @@ to_tsquery('simple', :q) "
                "ORDER BY rank DESC LIMIT :n"
            ),
            {"q": tsquery, "n": limit},
        ).fetchall()
        return [(r[0], float(r[1])) for r in rows]

    def _expand_query_tokens(self, query: str) -> list[str]:
        """Language-aware expansion (architecture 7.3): add cross-language terms."""
        base = [t.lower() for t in _WORD_RE.findall(query) if len(t) > 1]
        expanded = list(base)
        for tok in base:
            if tok in GLOSSARY:
                expanded.extend(GLOSSARY[tok].split())
        # de-dup preserving order
        seen = set()
        return [t for t in expanded if not (t in seen or seen.add(t))]

    def _rrf_fuse(
        self, dense: list[tuple[str, float]], sparse: list[tuple[str, float]]
    ) -> list[tuple[str, float]]:
        k = settings.rrf_k
        scores: dict[str, float] = {}
        for rank, (cid, _) in enumerate(dense):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
        for rank, (cid, _) in enumerate(sparse):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
        return sorted(scores.items(), key=lambda x: x[1], reverse=True)


_service: RetrievalService | None = None


def get_retrieval_service() -> RetrievalService:
    global _service
    if _service is None:
        _service = RetrievalService()
    return _service
