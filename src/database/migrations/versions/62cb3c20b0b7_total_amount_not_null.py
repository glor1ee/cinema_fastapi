"""Make orders.total_amount NOT NULL

Revision ID: 62cb3c20b0b7
Revises: e33b31fd8e87
Create Date: 2026-08-20 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '62cb3c20b0b7'
down_revision: Union[str, None] = 'e33b31fd8e87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE orders SET total_amount = 0 WHERE total_amount IS NULL")
    with op.batch_alter_table('orders') as batch_op:
        batch_op.alter_column('total_amount', existing_type=sa.DECIMAL(10, 2), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table('orders') as batch_op:
        batch_op.alter_column('total_amount', existing_type=sa.DECIMAL(10, 2), nullable=True)
