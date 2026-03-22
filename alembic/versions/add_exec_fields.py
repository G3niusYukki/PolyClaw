"""add order execution fields

Revision ID: add_exec_fields
Revises: 9ca76fdfabd0
Create Date: 2026-03-22 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'add_exec_fields'
down_revision: Union[str, None] = '9ca76fdfabd0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add execution fields to orders table
    op.add_column('orders', sa.Column('status_history', sa.JSON(), nullable=True))
    op.add_column('orders', sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('orders', sa.Column('updated_at', sa.DateTime(), nullable=True))

    # Add shadow/trading fields to positions table
    op.add_column('positions', sa.Column('is_shadow', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('positions', sa.Column('strategy_id', sa.String(length=128), nullable=False, server_default=''))

    # Create shadow_results table
    op.create_table(
        'shadow_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('market_id', sa.String(length=128), nullable=False),
        sa.Column('strategy_id', sa.String(length=128), nullable=False),
        sa.Column('predicted_side', sa.String(length=8), nullable=False),
        sa.Column('predicted_prob', sa.Float(), nullable=False),
        sa.Column('shadow_fill_price', sa.Float(), nullable=False),
        sa.Column('actual_outcome', sa.String(length=8), nullable=False),
        sa.Column('pnl', sa.Float(), nullable=False),
        sa.Column('accuracy', sa.Boolean(), nullable=False),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_shadow_results_market_id'), 'shadow_results', ['market_id'], unique=False)
    op.create_index(op.f('ix_shadow_results_strategy_id'), 'shadow_results', ['strategy_id'], unique=False)
    op.create_index(op.f('ix_shadow_results_accuracy'), 'shadow_results', ['accuracy'], unique=False)

    # Create trading_stage_records table
    op.create_table(
        'trading_stage_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('stage', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(length=256), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    # Create market_whitelist table
    op.create_table(
        'market_whitelist',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('market_id', sa.String(length=128), nullable=False),
        sa.Column('added_at', sa.DateTime(), nullable=False),
        sa.Column('added_reason', sa.String(length=256), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('market_id'),
    )
    op.create_index(op.f('ix_market_whitelist_market_id'), 'market_whitelist', ['market_id'], unique=True)


def downgrade() -> None:
    op.drop_table('market_whitelist')
    op.drop_table('trading_stage_records')
    op.drop_table('shadow_results')
    op.drop_column('positions', 'strategy_id')
    op.drop_column('positions', 'is_shadow')
    op.drop_column('orders', 'updated_at')
    op.drop_column('orders', 'retry_count')
    op.drop_column('orders', 'status_history')
