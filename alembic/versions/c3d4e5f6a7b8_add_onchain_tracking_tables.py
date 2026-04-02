"""add onchain tracking tables

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-02 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'wallet_tracking',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('address', sa.String(length=128), nullable=False),
        sa.Column('label', sa.String(length=128), nullable=False, server_default=''),
        sa.Column('is_profitable', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('total_pnl', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('first_seen_at', sa.DateTime(), nullable=False),
        sa.Column('last_active_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_wallet_tracking_address', 'wallet_tracking', ['address'], unique=True)

    op.create_table(
        'onchain_positions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('market_id', sa.String(length=128), nullable=False),
        sa.Column('wallet_address', sa.String(length=128), nullable=False),
        sa.Column('side', sa.String(length=8), nullable=False),
        sa.Column('size_usd', sa.Float(), nullable=False),
        sa.Column('outcome_tokens', sa.Float(), nullable=False, server_default='0'),
        sa.Column('observed_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_onchain_positions_market_id', 'onchain_positions', ['market_id'])
    op.create_index('ix_onchain_positions_wallet_address', 'onchain_positions', ['wallet_address'])

    op.create_table(
        'smart_money_signals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('market_id', sa.String(length=128), nullable=False),
        sa.Column('signal_type', sa.String(length=32), nullable=False),
        sa.Column('direction', sa.String(length=8), nullable=False),
        sa.Column('magnitude', sa.Float(), nullable=False),
        sa.Column('details', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('smart_money_signals')
    op.drop_index('ix_onchain_positions_wallet_address', table_name='onchain_positions')
    op.drop_index('ix_onchain_positions_market_id', table_name='onchain_positions')
    op.drop_table('onchain_positions')
    op.drop_index('ix_wallet_tracking_address', table_name='wallet_tracking')
    op.drop_table('wallet_tracking')
