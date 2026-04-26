from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class CreateSubjectRequest(BaseModel):
    name: str
    name_ml: str
    slug: str
    class_number: int
    icon: str
    color: str
    monthly_price_paise: int
    order_index: int = 0

    @field_validator("class_number")
    @classmethod
    def validate_class(cls, v: int) -> int:
        if v not in range(7, 11):
            raise ValueError("class_number must be 7–10")
        return v


class SubjectAdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    name_ml: str
    slug: str
    class_number: int
    icon: str
    color: str
    monthly_price_paise: int
    is_active: bool
    order_index: int
    created_at: datetime


class CreateChapterRequest(BaseModel):
    subject_id: UUID
    chapter_number: int
    title: str
    title_ml: str
    description: str | None = None
    order_index: int = 0


class ChapterAdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject_id: UUID
    chapter_number: int
    title: str
    title_ml: str
    description: str | None
    is_published: bool
    order_index: int
    created_at: datetime


class PublishToggleResponse(BaseModel):
    id: UUID
    is_published: bool


class QuestionInput(BaseModel):
    """A single MCQ question as submitted by the admin."""

    id: str
    text: str
    text_ml: str = ""
    options: list[str]
    correct_answer: int
    explanation: str = ""
    marks: int = 1

    @field_validator("options")
    @classmethod
    def four_options(cls, v: list[str]) -> list[str]:
        if len(v) != 4:
            raise ValueError("Each question must have exactly 4 options")
        return v

    @field_validator("correct_answer")
    @classmethod
    def valid_index(cls, v: int) -> int:
        if v not in range(4):
            raise ValueError("correct_answer must be 0, 1, 2, or 3")
        return v


class CreateTestRequest(BaseModel):
    chapter_id: UUID
    title: str
    duration_minutes: int = 30
    total_marks: int
    questions: list[QuestionInput]


class TestAdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    chapter_id: UUID
    title: str
    duration_minutes: int
    total_marks: int
    is_published: bool
    created_at: datetime


class NoteUploadResponse(BaseModel):
    id: UUID
    r2_key: str
    file_size_bytes: int


class RevenueDataPoint(BaseModel):
    date: str
    amount_paise: int


class AdminDashboardResponse(BaseModel):
    total_students: int
    active_subscriptions: int
    mrr_paise: int
    new_signups_today: int
    pending_doubts: int
    revenue_last_30_days: list[RevenueDataPoint]


class AdminStudentItem(BaseModel):
    id: UUID
    name: str
    phone: str | None
    email: str | None
    current_class: int | None
    subscription_status: str
    joined_at: datetime


class AdminStudentListResponse(BaseModel):
    total: int
    students: list[AdminStudentItem]


class AdminDoubtItem(BaseModel):
    id: UUID
    student_name: str
    question_text: str
    chapter_id: UUID | None
    lesson_id: UUID | None
    status: str
    created_at: datetime


class AdminDoubtListResponse(BaseModel):
    total: int
    doubts: list[AdminDoubtItem]


class SubjectChaptersAdminResponse(BaseModel):
    id: UUID
    name: str
    chapters: list[ChapterAdminResponse]
