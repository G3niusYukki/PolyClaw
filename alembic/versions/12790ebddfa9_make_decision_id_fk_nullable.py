"""make decision_id_fk nullable

Revision ID: 12790ebddfa9
Revises: add_exec_fields
Create Date: 2026-03-22 18:19:19.232692

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '12790ebddfa9'
down_revision: Union[str, None] = 'add_exec_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Make decision_id_fk nullable so orders can exist without a linked decision
    op.alter_column('orders', 'decision_id_fk', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.alter_column('orders', 'decision_id_fk', existing_type=sa.Integer(), nullable=False)
