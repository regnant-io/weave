"""Retrieval tests: ingest, hybrid search, language-aware expansion, flags."""
from __future__ import annotations

from app.models import Source
from app.services.retrieval import get_retrieval_service


def test_ingest_and_hybrid_search(db_session):
    svc = get_retrieval_service()
    src = Source(
        title="Test NBS Population Report", source_type="nbs", access_status="open",
        language="en", predatory_flag=False,
    )
    db_session.add(src)
    db_session.flush()
    n = svc.ingest_source(db_session, src, (
        "The population of Tanzania was about 61.7 million according to the 2022 census. "
        "The National Bureau of Statistics reported an annual growth rate of 3.2 percent.\n\n"
        "Agriculture employs the majority of the labour force in the country."
    ))
    assert n >= 1

    results = svc.search(db_session, "population of Tanzania census", language="en")
    assert results
    assert any("population" in r["content"].lower() for r in results)
    assert results[0]["access_status"] == "open"


def test_language_aware_expansion_surfaces_english_source(db_session):
    svc = get_retrieval_service()
    src = Source(
        title="Elimu Report", source_type="gov", access_status="open",
        language="en", predatory_flag=False,
    )
    db_session.add(src)
    db_session.flush()
    svc.ingest_source(db_session, src, (
        "This education policy document describes the secondary school curriculum "
        "and examination structure in the country."
    ))
    # Swahili query 'elimu' should expand to 'education' and hit the English source.
    results = svc.search(db_session, "sera ya elimu", language="sw")
    assert any("education" in r["content"].lower() for r in results)


def test_predatory_flag_surfaced(db_session):
    svc = get_retrieval_service()
    src = Source(
        title="Rapid Guaranteed Journal", source_type="journal", access_status="paywalled",
        language="en", predatory_flag=True,
    )
    db_session.add(src)
    db_session.flush()
    svc.ingest_source(db_session, src, "Guaranteed rapid publication upon payment of a fee.")
    results = svc.search(db_session, "guaranteed rapid publication fee", language="en")
    flagged = [r for r in results if r["predatory_flag"]]
    assert flagged
    assert flagged[0]["access_status"] == "paywalled"
