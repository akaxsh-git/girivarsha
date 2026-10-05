"""phase12_evacuation_and_replay

Revision ID: 6bbf03dc577b
Revises: 2cf18aba1900
Create Date: 2026-09-04 13:48:38.731828

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6bbf03dc577b'
down_revision: Union[str, None] = '2cf18aba1900'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'event_timeline_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('historical_event_id', sa.Integer(), nullable=False),
        sa.Column('sequence_order', sa.Integer(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('time_precision', sa.String(length=32), nullable=False),
        sa.Column('headline', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('source_citation', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['historical_event_id'], ['historical_events.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_event_timeline_entries_historical_event_id'),
        'event_timeline_entries',
        ['historical_event_id'],
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_event_timeline_entries_historical_event_id'), table_name='event_timeline_entries')
    op.drop_table('event_timeline_entries')
