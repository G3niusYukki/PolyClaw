"""add news and sentiment tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'news_articles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('market_id_fk', sa.Integer(), sa.ForeignKey('markets.id'), nullable=False),
        sa.Column('market_id', sa.String(length=128), nullable=False),
        sa.Column('title', sa.String(length=512), nullable=False),
        sa.Column('snippet', sa.Text(), nullable=False, server_default=''),
        sa.Column('source', sa.String(length=128), nullable=False, server_default=''),
        sa.Column('url', sa.String(length=512), nullable=False, server_default=''),
        sa.Column('published_at', sa.DateTime(), nullable=False),
        sa.Column('fetched_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_news_articles_market_id', 'news_articles', ['market_id'])

    op.create_table(
        'sentiment_scores',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('market_id', sa.String(length=128), nullable=False),
        sa.Column('direction', sa.String(length=16), nullable=False),
        sa.Column('magnitude', sa.Float(), nullable=False),
        sa.Column('adjusted_probability', sa.Float(), nullable=False),
        sa.Column('articles_analyzed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('key_insights', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_sentiment_scores_market_id', 'sentiment_scores', ['market_id'])


def downgrade() -> None:
    op.drop_index('ix_sentiment_scores_market_id', table_name='sentiment_scores')
    op.drop_table('sentiment_scores')
    op.drop_index('ix_news_articles_market_id', table_name='news_articles')
    op.drop_table('news_articles')
