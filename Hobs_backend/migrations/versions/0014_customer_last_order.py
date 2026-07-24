"""placeholder bridge for a removed historical revision

Revision ID: 0014_customer_last_order
Revises: 0002_fix_id_column_lengths
Create Date: 2026-06-16

WHY THIS FILE EXISTS — DO NOT DELETE
-------------------------------------
The original `0014_customer_last_order` migration (and the incremental
migrations before it, 0003-0013) added columns/tables that were later
folded directly into `0001_initial.py` during a history squash, and the
old incremental script files were deleted from this repo.

The squash assumed every database would be rebuilt from scratch. In
reality, the production database had already run the real
`0014_customer_last_order` migration and its `alembic_version` table is
still stamped with that exact revision id. With the script file gone,
`alembic upgrade head` could no longer locate that revision at all,
which made every deploy fail at the migration step (entrypoint.sh aborts
the container when migrations fail) — so no migration created after
this point, including `0016_onboarding_columns`, was ever actually
applied in production.

This file does nothing structurally (everything it once did is already
present in `0001_initial.py` for fresh databases, and already applied
directly for the existing production database). Its only job is to
exist as a valid node in Alembic's revision graph so:
  - a fresh database created from `0001` -> `0002` -> here -> `0015` ->
    `0016` ends up with the identical schema, and
  - the existing production database (currently stamped at this
    revision) can resolve forward to `0015` and `0016` again.

Keep this revision id exactly as-is and never reuse it.
"""
from alembic import op
import sqlalchemy as sa

revision      = "0014_customer_last_order"
down_revision = "0002_fix_id_column_lengths"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # No-op — see module docstring. The schema changes this revision
    # historically made are already part of 0001_initial.py.
    pass


def downgrade() -> None:
    # No-op for the same reason.
    pass
