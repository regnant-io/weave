"""Analysis Service (architecture 5.1 #4).

Owns dataset handling and the sandbox interface. It is the ONLY caller of the
Sandbox Manager, giving the sandbox a tight, auditable boundary (architecture 10:
least privilege — Analysis Service talks to the Sandbox Manager and S3, nothing
else).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from ...models import AnalysisRun, Dataset, SandboxAudit
from ...storage import storage
from ..sandbox import SandboxResult, get_sandbox_manager
from .profiling import profile_dataset


class AnalysisService:
    def __init__(self) -> None:
        self.sandbox = get_sandbox_manager()

    def profile(self, dataset: Dataset, db: Session) -> None:
        """Populate a dataset's profile from its stored object."""
        local = storage.local_path(dataset.s3_key)
        prof = profile_dataset(local)
        dataset.column_profile = prof
        dataset.row_count = prof.get("row_count")
        dataset.status = "ready" if prof.get("available") else "error"
        db.add(dataset)
        db.commit()

    def run_code(
        self,
        db: Session,
        code: str,
        dataset: Dataset | None,
        heavy: bool = False,
        user_id: str | None = None,
        message_id: str | None = None,
    ) -> AnalysisRun:
        """Execute code in the sandbox, persist output files to storage, record the
        AnalysisRun and a separate SandboxAudit entry (architecture 8.4 item 5)."""
        dataset_path: Path | None = None
        if dataset is not None:
            dataset_path = storage.local_path(dataset.s3_key)

        result: SandboxResult = self.sandbox.run(code, dataset_path=dataset_path, heavy=heavy)

        # persist output files to object storage; store references on the run
        output_refs = []
        run_id_prefix = f"analysis/{dataset.id if dataset else 'nodata'}"
        import base64

        for f in result.output_files:
            key = f"{run_id_prefix}/{_short()}_{f.name}"
            storage.put_bytes(key, base64.b64decode(f.data_b64))
            output_refs.append({"name": f.name, "s3_key": key, "mime": f.mime, "bytes": f.bytes})

        run = AnalysisRun(
            message_id=message_id,
            dataset_id=dataset.id if dataset else None,
            code=code,
            stdout=result.stdout,
            stderr=result.stderr,
            output_files=output_refs,
            execution_time_ms=result.execution_time_ms,
            status=result.status,
        )
        db.add(run)

        # audit log, stored via the same DB but conceptually a separate sink
        db.add(SandboxAudit(
            user_id=user_id,
            dataset_id=dataset.id if dataset else None,
            code_hash=result.code_hash,
            result_hash=result.result_hash,
            status=result.status,
            execution_time_ms=result.execution_time_ms,
            peak_memory_kb=result.peak_memory_kb,
        ))
        db.commit()
        db.refresh(run)
        return run


def _short() -> str:
    import uuid
    return uuid.uuid4().hex[:8]


_service: AnalysisService | None = None


def get_analysis_service() -> AnalysisService:
    global _service
    if _service is None:
        _service = AnalysisService()
    return _service
