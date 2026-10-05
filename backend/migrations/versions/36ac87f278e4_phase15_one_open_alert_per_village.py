"""phase15_one_open_alert_per_village

Real bug found live on the user's own machine (not a hypothetical): the
Authority dashboard's Active Alerts panel showed Kedarnath listed three
separate times, each its own open ORANGE row, while every other village
appeared once. `app/services/alerts_engine.py::sync_alert_for_village`
only ever guarded against duplicates with an in-app check-then-act
(SELECT for an existing open alert, then INSERT if none/different level)
— safe within one serialized request, but with no DB-level constraint
backing it up, two genuinely concurrent requests computing the SAME
village's risk around the same moment (an overlapping poll, a page
refresh fired while a previous slow `/risk/map` call was still in
flight — exactly the conditions the pre-performance-fix ~48s `/risk/map`
made likely) could both see "no open alert yet" and both insert one,
leaving multiple open rows for one village with nothing to ever collapse
them back to one.

This migration does two things:
  1. Collapses any duplicate open alerts that already exist for the same
     village (a real, live data problem on at least one deployment, not
     just a future risk) — keeping only the most recently issued open
     alert per village and marking the rest resolved right now, so
     upgrading doesn't itself get blocked by the very rows it's fixing.
  2. Adds a partial unique index enforcing "at most one open (unresolved)
     alert per village" at the database level, so the invariant
     `alerts_engine.py`'s own docstring already claims ("open one open
     Alert per village") is actually guaranteed, not just intended.
     `sync_alert_for_village` is updated alongside this migration to
     catch the resulting IntegrityError on a genuine race and adopt
     whichever request's alert actually won, instead of raising a 500.

Revision ID: 36ac87f278e4
Revises: 6bbf03dc577b
Create Date: 2026-09-06 18:42:01.399037

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '36ac87f278e4'
down_revision: Union[str, None] = '6bbf03dc577b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: data cleanup — for any village with more than one open
    # (resolved_at IS NULL) alert, keep only the most recently issued one
    # open and resolve the rest right now. Ordinary operation never
    # produces this (see alerts_engine.py's own dedup logic); this only
    # matters for a database that already has duplicates from the race
    # this migration closes.
    op.execute(
        """
        UPDATE alerts
        SET resolved_at = now()
        WHERE resolved_at IS NULL
          AND id NOT IN (
              SELECT DISTINCT ON (village_id) id
              FROM alerts
              WHERE resolved_at IS NULL
              ORDER BY village_id, issued_at DESC, id DESC
          )
        """
    )

    # Step 2: the actual fix — a partial unique index (Postgres-specific;
    # this project's own database is Postgres/PostGIS throughout, see
    # app/models/database.py) enforcing "at most one open alert per
    # village" at the data layer, so no future race can ever recreate the
    # bug step 1 just cleaned up.
    op.create_index(
        "ix_alerts_one_open_per_village",
        "alerts",
        ["village_id"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_alerts_one_open_per_village", table_name="alerts")
    # The step-1 data cleanup above is intentionally not reversed — there is
    # no reliable way to un-resolve the specific duplicate rows it closed
    # without guessing, and leaving genuinely-resolved duplicates resolved
    # is the safe default on a downgrade.
