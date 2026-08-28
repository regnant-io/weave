"""Citation-check route (architecture 5.2: POST /citations/check) — predatory
journal flagging (architecture 6.5)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Source, User
from ..schemas import CitationCheckRequest, CitationCheckResponse, SourcePassage
from ..services import citations as citation_tools

router = APIRouter()


@router.post("/check", response_model=CitationCheckResponse)
def check_citation(
    body: CitationCheckRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> CitationCheckResponse:
    flagged, reason = citation_tools.check_reference(body.reference)

    matched = None
    if body.source_id:
        src = db.query(Source).filter(Source.id == body.source_id).first()
        if src:
            flagged = flagged or src.predatory_flag
            if src.predatory_flag:
                reason = "Source is flagged as predatory in the library metadata. " + reason
            matched = SourcePassage(
                source_id=src.id, chunk_id="", title=src.title, url=src.url,
                source_type=src.source_type, access_status=src.access_status,
                language=src.language, predatory_flag=src.predatory_flag,
                content="", score=1.0,
            )
    return CitationCheckResponse(
        reference=body.reference, flagged_predatory=flagged, reason=reason, matched_source=matched,
    )
