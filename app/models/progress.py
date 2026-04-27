import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WatchHistory(Base):
    __tablename__ = "watch_history"
    __table_args__ = (
        UniqueConstraint("user_id", "lesson_id", name="uq_watch_history_user_lesson"),
        CheckConstraint("watch_percentage BETWEEN 0 AND 100", name="ck_watch_percentage"),
        Index("idx_watch_history_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
    )
    watch_percentage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_time_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_watched_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)


class Test(Base):
    __tablename__ = "tests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
    )
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lessons.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    total_marks: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    questions: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)

    subject: Mapped["Subject"] = relationship("Subject")  # type: ignore[name-defined]
    chapter: Mapped["Chapter"] = relationship("Chapter", back_populates="tests")  # type: ignore[name-defined]
    lesson: Mapped["Lesson | None"] = relationship("Lesson", back_populates="tests")  # type: ignore[name-defined]
    attempts: Mapped[list["TestAttempt"]] = relationship("TestAttempt", back_populates="test")


class TestAttempt(Base):
    __tablename__ = "test_attempts"
    __table_args__ = (Index("idx_test_attempts_user", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    test_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tests.id", ondelete="CASCADE"), nullable=False
    )
    answers: Mapped[dict] = mapped_column(JSONB, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    total_marks: Mapped[int] = mapped_column(Integer, nullable=False)
    percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    time_taken_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)

    test: Mapped["Test"] = relationship("Test", back_populates="attempts")


class ScoreTrajectory(Base):
    __tablename__ = "score_trajectory"
    __table_args__ = (
        UniqueConstraint("user_id", "subject_id", "week_start", name="uq_score_traj_user_subject_week"),
        Index("idx_score_traj_user", "user_id", "subject_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    avg_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)
