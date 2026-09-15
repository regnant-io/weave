"""durable control plane and vector index

Revision ID: c4686ae6bd44
Revises: a9583a2c2007
Create Date: 2026-09-11 20:19:28.417195

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4686ae6bd44'
down_revision: Union[str, Sequence[str], None] = 'a9583a2c2007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        from pgvector.sqlalchemy import Vector
        vector_type = Vector(384)
    else:
        vector_type = sa.JSON()
    op.add_column("source_chunks", sa.Column("embedding_vector", vector_type, nullable=True))
    if bind.dialect.name == "postgresql":
        op.execute(
            "UPDATE source_chunks SET embedding_vector = embedding::text::vector "
            "WHERE jsonb_array_length(embedding::jsonb) = 384"
        )
        op.execute(
            "CREATE INDEX source_chunk_embedding_hnsw_idx ON source_chunks "
            "USING hnsw (embedding_vector vector_cosine_ops)"
        )

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("owner_id", sa.String(32), nullable=False),
        sa.Column("project_id", sa.String(32), nullable=False, server_default=""),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False, server_default=""),
        sa.Column("resource_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("response", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("namespace", "owner_id", "project_id", "key",
                            name="uq_idempotency_scope_key"),
    )
    op.create_index("ix_idempotency_records_owner_id", "idempotency_records", ["owner_id"])

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("topic", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("dedupe_key", sa.String(128), unique=True, nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_outbox_events_topic", "outbox_events", ["topic"])
    op.create_index("ix_outbox_events_aggregate_id", "outbox_events", ["aggregate_id"])
    op.create_index("ix_outbox_events_status", "outbox_events", ["status"])

    op.create_table(
        "webhook_receipts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="received"),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "event_id", name="uq_webhook_provider_event"),
    )

    op.create_table(
        "job_records",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("owner_id", sa.String(32), nullable=False, server_default=""),
        sa.Column("project_id", sa.String(32), nullable=False, server_default=""),
        sa.Column("celery_task_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("progress", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_job_records_kind", "job_records", ["kind"])
    op.create_index("ix_job_records_owner_id", "job_records", ["owner_id"])
    op.create_index("ix_job_records_project_id", "job_records", ["project_id"])
    op.create_index("ix_job_records_status", "job_records", ["status"])


def downgrade() -> None:
    """Downgrade schema."""
    for name in ("ix_job_records_status", "ix_job_records_project_id",
                 "ix_job_records_owner_id", "ix_job_records_kind"):
        op.drop_index(name, table_name="job_records")
    op.drop_table("job_records")
    op.drop_table("webhook_receipts")
    for name in ("ix_outbox_events_status", "ix_outbox_events_aggregate_id",
                 "ix_outbox_events_topic"):
        op.drop_index(name, table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_idempotency_records_owner_id", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index("source_chunk_embedding_hnsw_idx", table_name="source_chunks")
    with op.batch_alter_table("source_chunks") as batch:
        batch.drop_column("embedding_vector")
