"""initial migration

Revision ID: 9ca76fdfabd0
Revises:
Create Date: 2026-03-22 16:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9ca76fdfabd0'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'markets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('market_id', sa.String(length=128), nullable=False),
        sa.Column('title', sa.String(length=512), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('outcome_yes_price', sa.Float(), nullable=False),
        sa.Column('outcome_no_price', sa.Float(), nullable=False),
        sa.Column('spread_bps', sa.Integer(), nullable=False),
        sa.Column('liquidity_usd', sa.Float(), nullable=False),
        sa.Column('volume_24h_usd', sa.Float(), nullable=False),
        sa.Column('category', sa.String(length=128), nullable=False),
        sa.Column('event_key', sa.String(length=256), nullable=False),
        sa.Column('closes_at', sa.DateTime(), nullable=True),
        sa.Column('fetched_at', sa.DateTime(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('market_id'),
    )
    op.create_index(op.f('ix_markets_market_id'), 'markets', ['market_id'], unique=True)
    op.create_index(op.f('ix_markets_fetched_at'), 'markets', ['fetched_at'], unique=False)

    op.create_table(
        'evidences',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('market_id_fk', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=128), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('direction', sa.String(length=16), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('url', sa.String(length=512), nullable=False),
        sa.Column('observed_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['market_id_fk'], ['markets.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'decisions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('market_id_fk', sa.Integer(), nullable=False),
        sa.Column('side', sa.String(length=8), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('model_probability', sa.Float(), nullable=False),
        sa.Column('market_implied_probability', sa.Float(), nullable=False),
        sa.Column('edge_bps', sa.Integer(), nullable=False),
        sa.Column('stake_usd', sa.Float(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('explanation', sa.Text(), nullable=False),
        sa.Column('risk_flags', sa.Text(), nullable=False),
        sa.Column('requires_approval', sa.Boolean(), nullable=False),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['market_id_fk'], ['markets.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'orders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('decision_id_fk', sa.Integer(), nullable=False),
        sa.Column('client_order_id', sa.String(length=128), nullable=False),
        sa.Column('mode', sa.String(length=16), nullable=False),
        sa.Column('side', sa.String(length=8), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('size', sa.Float(), nullable=False),
        sa.Column('notional_usd', sa.Float(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('venue_order_id', sa.String(length=128), nullable=False),
        sa.Column('submitted_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['decision_id_fk'], ['decisions.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('client_order_id'),
    )
    op.create_index(op.f('ix_orders_client_order_id'), 'orders', ['client_order_id'], unique=True)

    op.create_table(
        'positions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_key', sa.String(length=256), nullable=False),
        sa.Column('market_id', sa.String(length=128), nullable=False),
        sa.Column('side', sa.String(length=8), nullable=False),
        sa.Column('notional_usd', sa.Float(), nullable=False),
        sa.Column('avg_price', sa.Float(), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('opened_at', sa.DateTime(), nullable=False),
        sa.Column('is_open', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_positions_event_key'), 'positions', ['event_key'], unique=False)
    op.create_index(op.f('ix_positions_market_id'), 'positions', ['market_id'], unique=False)

    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('result', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'], unique=False)
    op.create_index(op.f('ix_audit_logs_created_at'), 'audit_logs', ['created_at'], unique=False)

    op.create_table(
        'proposal_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('market_id', sa.String(length=128), nullable=False),
        sa.Column('title', sa.String(length=512), nullable=False),
        sa.Column('suggested_side', sa.String(length=16), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('edge_bps', sa.Integer(), nullable=False),
        sa.Column('suggested_stake_usd', sa.Float(), nullable=False),
        sa.Column('explanation', sa.Text(), nullable=False),
        sa.Column('ranking_reasons', sa.Text(), nullable=False),
        sa.Column('evidence_summaries', sa.Text(), nullable=False),
        sa.Column('risk_flags', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_proposal_records_market_id'), 'proposal_records', ['market_id'], unique=False)
    op.create_index(op.f('ix_proposal_records_status'), 'proposal_records', ['status'], unique=False)
    op.create_index(op.f('ix_proposal_records_created_at'), 'proposal_records', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_table('proposal_records')
    op.drop_table('audit_logs')
    op.drop_table('positions')
    op.drop_table('orders')
    op.drop_table('decisions')
    op.drop_table('evidences')
    op.drop_table('markets')
