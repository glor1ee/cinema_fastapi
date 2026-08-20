"""Seed user groups

Revision ID: e33b31fd8e87
Revises: f2dfbd1d4387
Create Date: 2026-08-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'e33b31fd8e87'
down_revision: Union[str, None] = 'f2dfbd1d4387'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("INSERT INTO user_groups (name) VALUES ('USER'), ('MODERATOR'), ('ADMIN')")


def downgrade() -> None:
    op.execute("DELETE FROM user_groups WHERE name IN ('USER', 'MODERATOR', 'ADMIN')")
