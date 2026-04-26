"""add token blacklist

Revision ID: b7c9f2a3e854
Revises: 3c170de11994
Create Date: 2026-04-26 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7c9f2a3e854"
down_revision: Union[str, None] = "3c170de11994"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "token_blacklist",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("jti", sa.String(36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("jti", name="uq_token_blacklist_jti"),
    )
    op.create_index("ix_token_blacklist_jti", "token_blacklist", ["jti"])


def downgrade() -> None:
    op.drop_index("ix_token_blacklist_jti", table_name="token_blacklist")
    op.drop_table("token_blacklist")
