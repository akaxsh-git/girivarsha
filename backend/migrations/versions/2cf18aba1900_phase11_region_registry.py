"""phase11_region_registry

Revision ID: 2cf18aba1900
Revises: 3df282548b2e
Create Date: 2026-09-04 13:12:25.526079

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '2cf18aba1900'
down_revision: Union[str, None] = '3df282548b2e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "regions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("states", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "source",
            postgresql.ENUM("REAL", "SIMULATED", "DERIVED", name="datasource", create_type=False),
            nullable=False,
        ),
        sa.Column("provenance", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.add_column("micro_catchments", sa.Column("region_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_micro_catchments_region_id_regions",
        "micro_catchments",
        "regions",
        ["region_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_micro_catchments_region_id_regions", "micro_catchments", type_="foreignkey")
    op.drop_column("micro_catchments", "region_id")
    op.drop_table("regions")
