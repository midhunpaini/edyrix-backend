"""add watch history current time

Revision ID: e5a6b7c8d9f0
Revises: d4f1a2b3c4d5
Create Date: 2026-04-26 19:40:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5a6b7c8d9f0"
down_revision: Union[str, None] = "d4f1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "watch_history",
        sa.Column(
            "current_time_seconds",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.alter_column("watch_history", "current_time_seconds", server_default=None)


def downgrade() -> None:
    op.drop_column("watch_history", "current_time_seconds")
