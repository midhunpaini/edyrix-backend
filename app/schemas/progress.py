from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class WatchHeartbeatRequest(BaseModel):
    lesson_id: UUID
    percentage: int
    current_time_seconds: int = 0


class WatchHeartbeatResponse(BaseModel):
    is_completed: bool


class SubjectProgress(BaseModel):
    subject_id: UUID
    name: str
    chapters_completed: int
    chapters_total: int
    percentage: int


class ProgressSummaryResponse(BaseModel):
    overall_percentage: int
    subjects: list[SubjectProgress]


class LessonProgress(BaseModel):
    lesson_id: UUID
    watch_percentage: int
    is_completed: bool


class ChapterProgressResponse(BaseModel):
    chapter_id: UUID
    lessons_completed: int
    lessons_total: int
    percentage: int
    lessons: list[LessonProgress]


class LastAttempt(BaseModel):
    score: int
    total_marks: int | None = None
    percentage: Decimal
    completed_at: datetime


class TestSummaryResponse(BaseModel):
    id: UUID
    title: str
    subject_id: UUID | None = None
    subject_name: str | None = None
    chapter_id: UUID
    chapter_number: int | None = None
    chapter_title: str | None = None
    lesson_id: UUID | None = None
    lesson_title: str | None = None
    duration_minutes: int
    total_marks: int
    question_count: int
    is_unlocked: bool = True
    unlock_reason: str | None = None
    last_attempt: LastAttempt | None


class AvailableTestItem(BaseModel):
    id: UUID
    title: str
    subject_id: UUID
    subject_name: str
    chapter_id: UUID
    chapter_number: int
    chapter_title: str
    lesson_id: UUID
    lesson_title: str
    duration_minutes: int
    total_marks: int
    question_count: int
    is_unlocked: bool
    unlock_reason: str | None = None
    last_attempt: LastAttempt | None


class TestQuestion(BaseModel):
    id: str
    text: str
    text_ml: str
    options: list[str]
    marks: int


class TestDetailResponse(BaseModel):
    id: UUID
    title: str
    subject_id: UUID
    subject_name: str
    chapter_id: UUID
    chapter_number: int
    chapter_title: str
    lesson_id: UUID
    lesson_title: str
    duration_minutes: int
    total_marks: int
    questions: list[TestQuestion]


class SubmitTestRequest(BaseModel):
    answers: dict[str, int]
    time_taken_seconds: int


class QuestionResult(BaseModel):
    question_id: str
    your_answer: int
    correct_answer: int
    is_correct: bool
    explanation: str


class SubmitTestResponse(BaseModel):
    attempt_id: UUID
    score: int
    total_marks: int
    percentage: Decimal
    results: list[QuestionResult]


class TestHistoryItem(BaseModel):
    attempt_id: UUID
    test_title: str
    score: int
    total_marks: int
    percentage: Decimal
    completed_at: datetime


class ScoreWeek(BaseModel):
    week_start: date
    avg_score: Decimal
    attempt_count: int


class SubjectTrajectory(BaseModel):
    subject_id: UUID
    subject_name: str
    weeks: list[ScoreWeek]
