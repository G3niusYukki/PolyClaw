"""add llm_estimates table

Revision ID: a1b2c3d4e5f6
Revises: 12790ebddfa9
Create Date: 2026-04-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '12790ebddfa9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'llm_estimates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('market_id_fk', sa.Integer(), sa.ForeignKey('markets.id'), nullable=False),
        sa.Column('market_id', sa.String(length=128), nullable=False),
        sa.Column('estimated_probability_yes', sa.Float(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('reasoning', sa.Text(), nullable=False, server_default=''),
        sa.Column('key_factors', sa.Text(), nullable=False, server_default=''),
        sa.Column('model', sa.String(length=128), nullable=False, server_default=''),
        sa.Column('provider', sa.String(length=64), nullable=False, server_default=''),
        sa.Column('raw_response', sa.Text(), nullable=False, server_default=''),
        sa.Column('token_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_llm_estimates_market_id', 'llm_estimates', ['market_id'])
    op.create_index('ix_llm_estimates_created_at', 'llm_estimates', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_llm_estimates_created_at', table_name='llm_estimates')
    op.drop_index('ix_llm_estimates_market_id', table_name='llm_estimates')
    op.drop_table('llm_estimates')
