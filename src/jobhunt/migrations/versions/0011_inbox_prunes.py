"""Inbox prunes: the operational record of each prune of discardable companions.

Revision ID: 0011
Revises: 0010_baseline
Create Date: 2026-10-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from jobhunt.db import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inbox_prunes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("inbox", sa.Text(), nullable=False),
        sa.Column("started_at", UTCDateTime(), nullable=False),
        sa.Column("finished_at", UTCDateTime(), nullable=False),
        sa.Column("removed", sa.Integer(), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("problems", sa.Integer(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("inbox_prunes", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_inbox_prunes_inbox"), ["inbox"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("inbox_prunes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_inbox_prunes_inbox"))
    op.drop_table("inbox_prunes")
