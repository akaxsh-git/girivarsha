"""phase17_sensor_api_keys

IoT device-authentication follow-up (user-requested): the ingestion
endpoint (POST /sensor-reading) previously trusted any request naming a
registered external_device_id, with no credential check at all — flagged
as an open gap in docs/IoT_Architecture.md's "Sensor authentication"
section since Phase 8. This adds a per-device API key (stored only as a
SHA-256 hash — the plaintext is generated once at provisioning time and
never persisted) that app/api/routes/sensors.py now checks whenever a
sensor has one set.

Nullable, not optional: this column is added to a table that may already
have real rows from a prior session's scripts/seed_iot_nodes.py run, with
no known plaintext key for any of them. A NULL here means "provisioned
before this feature existed" — that sensor's ingestion requests keep
working un-authenticated (the exact pre-migration behavior, unchanged)
until an operator runs scripts/rotate_sensor_api_keys.py to actually
secure it. Nothing is retroactively locked out by this migration alone.

Revision ID: 5dbcb12077f4
Revises: 72bf1653bf49
Create Date: 2026-09-07 17:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5dbcb12077f4'
down_revision: Union[str, None] = '72bf1653bf49'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sensors",
        sa.Column("api_key_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sensors", "api_key_hash")
