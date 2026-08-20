"""Seed user groups

Revision ID: e33b31fd8e87
Revises: f2dfbd1d4387
Create Date: 2026-08-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e33b31fd8e87'
down_revision: Union[str, None] = 'f2dfbd1d4387'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


user_groups_table = sa.table(
    'user_groups',
    sa.column('name', sa.String),
)


def upgrade() -> None:
    op.bulk_insert(user_groups_table, [{'name': 'user'}, {'name': 'moderator'}, {'name': 'admin'}])


def downgrade() -> None:
    op.execute(user_groups_table.delete().where(user_groups_table.c.name.in_(['user', 'moderator', 'admin'])))
