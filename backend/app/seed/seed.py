"""Seed the database with a demo user, an institution, the curated source
library (ingested + embedded), and a sample dataset + project.

Run:  python -m app.seed.seed
Idempotent: safe to run repeatedly.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..db import SessionLocal, init_db
from ..models import Dataset, Institution, Project, Source, User
from ..security import hash_password
from ..services.analysis import get_analysis_service
from ..services.retrieval import get_retrieval_service
from ..storage import storage

DEMO_PHONE = "+255700000001"
DEMO_PASSWORD = "weave-demo-123"

SAMPLE_CSV = """region,household_size,water_distance_m,monthly_income_tzs,diarrhea_cases,fertilizer_kg,maize_yield_kg_ha
Dodoma,5,450,180000,2,50,1400
Mwanza,6,1200,140000,5,20,900
Arusha,4,300,260000,1,80,1900
Mbeya,7,800,160000,4,35,1200
Iringa,5,600,210000,2,60,1600
Tabora,8,1500,120000,6,10,750
Kigoma,6,1100,130000,5,15,820
Morogoro,5,500,200000,2,55,1550
Singida,7,1300,110000,6,12,780
Ruvuma,4,400,230000,1,70,1750
Kagera,6,900,150000,3,30,1100
Mtwara,5,700,175000,3,45,1300
"""


def seed() -> None:
    init_db()
    db = SessionLocal()
    try:
        # institution
        inst = db.query(Institution).filter(Institution.name == "University of Dar es Salaam").first()
        if not inst:
            inst = Institution(name="University of Dar es Salaam", type="university",
                               curriculum_tag=None)
            db.add(inst)
            db.flush()

        # demo user
        user = db.query(User).filter(User.phone == DEMO_PHONE).first()
        if not user:
            user = User(
                phone=DEMO_PHONE, email="demo@weave.tz",
                password_hash=hash_password(DEMO_PASSWORD),
                role="both", preferred_language="sw", trust_tier="institutional",
                phone_verified=True, institution_id=inst.id,
            )
            db.add(user)
            db.flush()
            print(f"  demo user: {DEMO_PHONE} / {DEMO_PASSWORD}")

        # source library
        retrieval = get_retrieval_service()
        sources_path = Path(__file__).with_name("sources.json")
        entries = json.loads(sources_path.read_text(encoding="utf-8"))
        for e in entries:
            existing = db.query(Source).filter(Source.title == e["title"]).first()
            if existing:
                continue
            src = Source(
                title=e["title"], url=e.get("url"), source_type=e["source_type"],
                access_status=e["access_status"], language=e["language"],
                predatory_flag=e["predatory_flag"], publication_date=e.get("publication_date"),
            )
            db.add(src)
            db.flush()
            n = retrieval.ingest_source(db, src, e["text"])
            print(f"  ingested source: {e['title'][:50]}… ({n} chunks)")

        # sample project + dataset
        project = db.query(Project).filter(
            Project.user_id == user.id, Project.title == "Sample: Rural water & health"
        ).first()
        if not project:
            project = Project(
                user_id=user.id, title="Sample: Rural water & health",
                mode="researcher", hypotheses=[{
                    "text_sw": "Umbali wa chanzo cha maji una uhusiano na matukio ya kuhara.",
                    "text_en": "Distance to water source is associated with diarrhea incidence.",
                    "status": "open",
                }], summary="",
            )
            db.add(project)
            db.flush()

            key = f"datasets/{project.id}/sample.csv"
            storage.put_bytes(key, SAMPLE_CSV.encode("utf-8"))
            ds = Dataset(
                project_id=project.id, s3_key=key, original_filename="rural_water_health.csv",
                size_bytes=len(SAMPLE_CSV), status="profiling",
            )
            db.add(ds)
            db.flush()
            get_analysis_service().profile(ds, db)
            print(f"  sample dataset profiled: {ds.row_count} rows")

        db.commit()
        print("Seed complete.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
