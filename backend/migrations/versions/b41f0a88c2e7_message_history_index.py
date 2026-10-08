"""Index chronological thread history for bounded message paging.

Revision ID: b41f0a88c2e7
Revises: c4686ae6bd44
Create Date: 2026-09-24 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "b41f0a88c2e7"
down_revision: Union[str, Sequence[str], None] = "c4686ae6bd44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    indexes = (
        ("ix_message_thread_created_id", "messages", ["thread_id", "created_at", "id"]),
        ("ix_message_project_created", "messages", ["project_id", "created_at"]),
        ("ix_project_user_created_id", "projects", ["user_id", "created_at", "id"]),
    )
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            for name, table, columns in indexes:
                op.create_index(name, table, columns, postgresql_concurrently=True)
    else:
        for name, table, columns in indexes:
            op.create_index(name, table, columns)


def downgrade() -> None:
    bind = op.get_bind()
    indexes = (
        ("ix_message_thread_created_id", "messages"),
        ("ix_message_project_created", "messages"),
        ("ix_project_user_created_id", "projects"),
    )
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            for name, table in indexes:
                op.drop_index(name, table_name=table, postgresql_concurrently=True)
    else:
        for name, table in indexes:
            op.drop_index(name, table_name=table)
