"""Eval sets: each labelled posting's set (dev or holdout) and how it was decided, stored on posting_triage.

Upgrading gives every posting whose labelling was ever flagged complete the set the held-out start gave it
(holdout when first flagged after a recorded start, else dev), origin 'before-random', and deletes the
eval.holdout_start setting. Downgrading drops both columns and doesn't restore the start, so every labelled
posting then reports in one set until a held-out set is started again.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-29

"""
from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from jobhunt.db import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

triage = sa.table(
    "posting_triage",
    sa.column("job_id", sa.Integer),
    sa.column("skills_first_complete_at", UTCDateTime),
    sa.column("eval_set", sa.Text),
    sa.column("eval_set_origin", sa.Text),
)
settings = sa.table("app_settings", sa.column("key", sa.Text), sa.column("value", sa.Text))


def upgrade() -> None:
    with op.batch_alter_table("posting_triage", schema=None) as batch_op:
        batch_op.add_column(sa.Column("eval_set", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("eval_set_origin", sa.Text(), nullable=True))

    conn = op.get_bind()
    stored = conn.execute(sa.select(settings.c.value).where(settings.c.key == "eval.holdout_start")).scalar()
    start = datetime.fromisoformat(stored) if stored else None
    rows = conn.execute(
        sa.select(triage.c.job_id, triage.c.skills_first_complete_at).where(
            triage.c.skills_first_complete_at.is_not(None)
        )
    ).all()
    for job_id, first in rows:
        name = "holdout" if start is not None and first > start else "dev"
        conn.execute(
            sa.update(triage).where(triage.c.job_id == job_id).values(eval_set=name, eval_set_origin="before-random")
        )
    conn.execute(sa.delete(settings).where(settings.c.key == "eval.holdout_start"))


def downgrade() -> None:
    with op.batch_alter_table("posting_triage", schema=None) as batch_op:
        batch_op.drop_column("eval_set_origin")
        batch_op.drop_column("eval_set")
