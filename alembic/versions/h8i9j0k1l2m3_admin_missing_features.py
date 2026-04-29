"""admin missing features

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-04-28 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "h8i9j0k1l2m3"
down_revision: Union[str, None] = "g7h8i9j0k1l2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users: suspension fields ──
    op.add_column("users", sa.Column("is_suspended", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("users", sa.Column("suspended_at", postgresql.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("users", sa.Column("suspended_reason", sa.Text(), nullable=True))

    # ── lessons: soft-delete ──
    op.add_column("lessons", sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("lessons", sa.Column("deleted_at", postgresql.TIMESTAMP(timezone=True), nullable=True))
    op.create_index("idx_lessons_deleted", "lessons", ["is_deleted"], postgresql_where=sa.text("is_deleted = false"))

    # ── doubts: assignment + SLA ──
    op.add_column("doubts", sa.Column("assigned_to", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("doubts", sa.Column("closed_at", postgresql.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("doubts", sa.Column("close_reason", sa.String(50), nullable=True))
    op.add_column("doubts", sa.Column("sla_breached", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.create_foreign_key("fk_doubts_assigned_to", "doubts", "users", ["assigned_to"], ["id"])
    op.create_index("idx_doubts_assigned", "doubts", ["assigned_to"])
    op.create_index("idx_doubts_status_sla", "doubts", ["status", "created_at"])

    # ── notification_logs ──
    op.create_table(
        "notification_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("target_segment", sa.String(50), nullable=False),
        sa.Column("target_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("scheduled_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("sent_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_notif_status", "notification_logs", ["status", "created_at"])

    # ── audit_logs ──
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("admin_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("changes", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_audit_admin", "audit_logs", ["admin_id", "created_at"])

    # ── doubt_templates ──
    op.create_table(
        "doubt_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("admin_users.id"), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("doubt_templates")
    op.drop_index("idx_audit_admin", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("idx_notif_status", table_name="notification_logs")
    op.drop_table("notification_logs")
    op.drop_index("idx_doubts_status_sla", table_name="doubts")
    op.drop_index("idx_doubts_assigned", table_name="doubts")
    op.drop_constraint("fk_doubts_assigned_to", "doubts", type_="foreignkey")
    op.drop_column("doubts", "sla_breached")
    op.drop_column("doubts", "close_reason")
    op.drop_column("doubts", "closed_at")
    op.drop_column("doubts", "assigned_to")
    op.drop_index("idx_lessons_deleted", table_name="lessons")
    op.drop_column("lessons", "deleted_at")
    op.drop_column("lessons", "is_deleted")
    op.drop_column("users", "suspended_reason")
    op.drop_column("users", "suspended_at")
    op.drop_column("users", "is_suspended")
