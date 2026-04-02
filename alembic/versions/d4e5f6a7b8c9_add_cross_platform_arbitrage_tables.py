"""add cross-platform arbitrage tables

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-02 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'cross_platform_prices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('market_id', sa.String(length=128), nullable=False),
        sa.Column('platform', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=512), nullable=False),
        sa.Column('probability_yes', sa.Float(), nullable=False),
        sa.Column('volume_usd', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('url', sa.String(length=512), nullable=False, server_default=''),
        sa.Column('similarity_score', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('fetched_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_cross_platform_prices_market_id', 'cross_platform_prices', ['market_id'])

    op.create_table(
        'arbitrage_opportunities',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('market_id', sa.String(length=128), nullable=False),
        sa.Column('discrepancy_bps', sa.Integer(), nullable=False),
        sa.Column('polymarket_price', sa.Float(), nullable=False),
        sa.Column('consensus_price', sa.Float(), nullable=False),
        sa.Column('platforms_agreeing', sa.Integer(), nullable=False),
        sa.Column('platform_list', sa.String(length=256), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('arbitrage_opportunities')
    op.drop_index('ix_cross_platform_prices_market_id', table_name='cross_platform_prices')
    op.drop_table('cross_platform_prices')
