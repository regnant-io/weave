"""Merge the auth and performance migration branches.

Revision ID: f60d40a61dd2
Revises: b41f0a88c2e7, e9d98a351087
Create Date: 2026-09-24 00:00:00.000000
"""
from typing import Sequence, Union


revision: str = "f60d40a61dd2"
down_revision: Union[str, Sequence[str], None] = (
    "b41f0a88c2e7",
    "e9d98a351087",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
