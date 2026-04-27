"""retention features

Revision ID: g7h8i9j0k1l2
Revises: f6a7b8c9d0e1
Create Date: 2026-04-27 09:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "g7h8i9j0k1l2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- users: add onboarding_complete + exam_date ---
    op.add_column("users", sa.Column("onboarding_complete", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("users", sa.Column("exam_date", sa.Date(), nullable=True))

    # --- user_goals ---
    op.create_table(
        "user_goals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("exam_date", sa.Date(), nullable=True),
        sa.Column("daily_minutes", sa.SmallInteger(), nullable=False, server_default="30"),
        sa.Column("target_score", sa.SmallInteger(), nullable=False, server_default="70"),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # --- share_events ---
    op.create_table(
        "share_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("platform", sa.String(20), nullable=False, server_default="whatsapp"),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_share_events_user", "share_events", ["user_id"])

    # --- score_trajectory ---
    op.create_table(
        "score_trajectory",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("avg_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "subject_id", "week_start", name="uq_score_traj_user_subject_week"),
    )
    op.create_index("idx_score_traj_user", "score_trajectory", ["user_id", "subject_id"])


def downgrade() -> None:
    op.drop_index("idx_score_traj_user", table_name="score_trajectory")
    op.drop_table("score_trajectory")
    op.drop_index("idx_share_events_user", table_name="share_events")
    op.drop_table("share_events")
    op.drop_table("user_goals")
    op.drop_column("users", "exam_date")
    op.drop_column("users", "onboarding_complete")
