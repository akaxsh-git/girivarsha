"""phase16_notification_subscriptions

SMS-reach follow-up (user-requested): a villager or authority can opt a
phone number in to get an SMS when one specific village crosses into
ORANGE/RED — see app/services/notifications.py and
app/providers/notification.py. No account/auth system exists yet (same
MVP-appropriate posture already documented for User/RBAC in
docs/Limitations.md), so this table needs only a village + phone number,
not a login.

Revision ID: 72bf1653bf49
Revises: 36ac87f278e4
Create Date: 2026-09-06 19:26:28.438207

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '72bf1653bf49'
down_revision: Union[str, None] = '36ac87f278e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("village_id", sa.Integer(), sa.ForeignKey("villages.id"), nullable=False),
        sa.Column("phone_number", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unsubscribed_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Lookups are always "active subscriptions for this village" (see
    # notifications.py::active_subscriptions_for_village) — a plain index on
    # village_id, not a unique one, since unsubscribing then re-subscribing
    # the same number is expected to leave more than one historical row.
    op.create_index(
        "ix_notification_subscriptions_village_id",
        "notification_subscriptions",
        ["village_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_notification_subscriptions_village_id", table_name="notification_subscriptions")
    op.drop_table("notification_subscriptions")
