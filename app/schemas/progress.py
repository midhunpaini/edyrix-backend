from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class WatchHeartbeatRequest(BaseModel):
    lesson_id: UUID
    percentage: int


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


class TestSummaryResponse(BaseModel):
    id: UUID
    title: str
    duration_minutes: int
    total_marks: int
    question_count: int
    last_attempt: "LastAttempt | None"


class LastAttempt(BaseModel):
    score: int
    percentage: Decimal
    completed_at: datetime


TestSummaryResponse.model_rebuild()


class TestQuestion(BaseModel):
    id: str
    text: str
    text_ml: str
    options: list[str]
    marks: int


class TestDetailResponse(BaseModel):
    id: UUID
    title: str
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
