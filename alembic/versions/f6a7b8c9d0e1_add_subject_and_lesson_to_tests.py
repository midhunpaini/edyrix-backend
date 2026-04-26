"""add subject and lesson to tests

Revision ID: f6a7b8c9d0e1
Revises: e5a6b7c8d9f0
Create Date: 2026-04-26 20:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5a6b7c8d9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tests", sa.Column("subject_id", sa.UUID(as_uuid=True), nullable=True))
    op.add_column("tests", sa.Column("lesson_id", sa.UUID(as_uuid=True), nullable=True))

    op.execute(
        """
        UPDATE tests
        SET subject_id = chapters.subject_id
        FROM chapters
        WHERE tests.chapter_id = chapters.id
          AND tests.subject_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE tests
        SET lesson_id = revision_lessons.id
        FROM (
            SELECT DISTINCT ON (chapter_id) id, chapter_id
            FROM lessons
            WHERE order_index = 5
            ORDER BY chapter_id, created_at, id
        ) AS revision_lessons
        WHERE tests.chapter_id = revision_lessons.chapter_id
          AND tests.lesson_id IS NULL
        """
    )

    op.alter_column("tests", "subject_id", nullable=False)
    op.create_foreign_key("fk_tests_subject_id", "tests", "subjects", ["subject_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_tests_lesson_id", "tests", "lessons", ["lesson_id"], ["id"], ondelete="CASCADE")
    op.create_index("idx_tests_subject", "tests", ["subject_id"])
    op.create_index("idx_tests_lesson", "tests", ["lesson_id"])


def downgrade() -> None:
    op.drop_index("idx_tests_lesson", table_name="tests")
    op.drop_index("idx_tests_subject", table_name="tests")
    op.drop_constraint("fk_tests_lesson_id", "tests", type_="foreignkey")
    op.drop_constraint("fk_tests_subject_id", "tests", type_="foreignkey")
    op.drop_column("tests", "lesson_id")
    op.drop_column("tests", "subject_id")
