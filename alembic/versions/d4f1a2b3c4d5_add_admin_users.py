"""add admin users

Revision ID: d4f1a2b3c4d5
Revises: c3d8e1f2a901
Create Date: 2026-04-26 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4f1a2b3c4d5"
down_revision: Union[str, None] = "c3d8e1f2a901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_users",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_admin_users_email", "admin_users", ["email"])
    op.add_column("doubts", sa.Column("answered_by_admin_id", sa.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_doubts_answered_by_admin_id",
        "doubts",
        "admin_users",
        ["answered_by_admin_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_doubts_answered_by_admin_id", "doubts", type_="foreignkey")
    op.drop_column("doubts", "answered_by_admin_id")
    op.drop_index("ix_admin_users_email", table_name="admin_users")
    op.drop_table("admin_users")
