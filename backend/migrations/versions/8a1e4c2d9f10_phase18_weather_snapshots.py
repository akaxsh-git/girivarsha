"""phase18_weather_snapshots

Hourly real Open-Meteo readings written by scripts/fetch_weather_snapshot.py
(run on a schedule by .github/workflows/weather-snapshot.yml). The hosted
backend's outbound IP is shared with many other apps on its free tier, so
Open-Meteo's per-IP free quota is exhausted by others and live calls get
HTTP 429. The scheduled job fetches from a different machine each run and
stores the result here; RealRainfallProvider/RealSoilMoistureProvider read a
fresh row first (see app/providers/weather_cache.py) and only call Open-Meteo
live when no fresh row exists.

One row per (kind, rounded point); upserted each run.

Revision ID: 8a1e4c2d9f10
Revises: 5dbcb12077f4
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "8a1e4c2d9f10"
down_revision: Union[str, None] = "5dbcb12077f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "weather_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),  # 'rainfall' | 'soil_moisture'
        sa.Column("lat_key", sa.Float(), nullable=False),  # rounded to 3 dp (~110 m)
        sa.Column("lon_key", sa.Float(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(64), nullable=False),
        sa.Column("model_time", sa.String(32), nullable=True),  # Open-Meteo's own timestamp
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_name", sa.String(64), nullable=False),
        sa.UniqueConstraint("kind", "lat_key", "lon_key", name="uq_weather_snapshot_point"),
    )
    op.create_index("ix_weather_snapshots_kind_fetched", "weather_snapshots", ["kind", "fetched_at"])


def downgrade() -> None:
    op.drop_index("ix_weather_snapshots_kind_fetched", table_name="weather_snapshots")
    op.drop_table("weather_snapshots")
