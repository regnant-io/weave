"""Library / retrieval routes (architecture 5.2: GET /library/search).

Anonymous browsing is allowed at low rate limits (architecture 5.3); chat/analysis
require a verified account, but reading the curated library does not."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import enforce_anon_limit
from ..models import Source
from ..schemas import LibrarySearchResponse, SourcePassage
from ..services.retrieval import get_retrieval_service

router = APIRouter()


@router.get("/search", response_model=LibrarySearchResponse)
def search_library(
    q: str = Query(..., min_length=1),
    language: str = Query("sw"),
    source: str | None = Query(None, description="comma-separated source types e.g. costech,udsm,nbs"),
    db: Session = Depends(get_db),
    _user=Depends(enforce_anon_limit),
) -> LibrarySearchResponse:
    source_types = [s.strip() for s in source.split(",")] if source else None
    results = get_retrieval_service().search(db, q, language=language, source_types=source_types)
    return LibrarySearchResponse(
        query=q, language=language,
        results=[SourcePassage(**r) for r in results],
    )


@router.get("/sources", response_model=list[dict])
def list_sources(db: Session = Depends(get_db), _user=Depends(enforce_anon_limit)):
    sources = db.query(Source).order_by(Source.title).all()
    return [
        {
            "id": s.id, "title": s.title, "url": s.url, "source_type": s.source_type,
            "access_status": s.access_status, "language": s.language,
            "predatory_flag": s.predatory_flag, "publication_date": s.publication_date,
        }
        for s in sources
    ]
