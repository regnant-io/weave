"""auth sessions and admin invitations

Revision ID: e9d98a351087
Revises: c4686ae6bd44
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "e9d98a351087"
down_revision: Union[str, Sequence[str], None] = "c4686ae6bd44"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("family_id", sa.String(32), nullable=False),
        sa.Column("refresh_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("replaced_by_id", sa.String(32), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("user_id", "family_id", "refresh_hash"):
        op.create_index(f"ix_auth_sessions_{column}", "auth_sessions", [column])
    op.create_table(
        "admin_invitations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("invited_by", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_admin_invitations_token_hash", "admin_invitations", ["token_hash"])


def downgrade() -> None:
    op.drop_index("ix_admin_invitations_token_hash", table_name="admin_invitations")
    op.drop_table("admin_invitations")
    for column in ("refresh_hash", "family_id", "user_id"):
        op.drop_index(f"ix_auth_sessions_{column}", table_name="auth_sessions")
    op.drop_table("auth_sessions")
