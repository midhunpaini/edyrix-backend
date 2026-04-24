from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ClassSummary(BaseModel):
    class_number: int
    label: str
    subject_count: int


class SubjectListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    name_ml: str
    slug: str
    icon: str
    color: str
    chapter_count: int
    monthly_price_paise: int
    has_access: bool
    watch_percentage: int


class ChapterSummary(BaseModel):
    id: UUID
    chapter_number: int
    title: str
    title_ml: str
    lesson_count: int
    has_test: bool
    watch_percentage: int
    is_completed: bool


class SubjectDetailResponse(BaseModel):
    id: UUID
    name: str
    name_ml: str
    slug: str
    icon: str
    color: str
    chapter_count: int
    monthly_price_paise: int
    has_access: bool
    watch_percentage: int
    chapters: list[ChapterSummary]


class LessonSummary(BaseModel):
    id: UUID
    title: str
    duration_seconds: int | None
    is_free: bool
    thumbnail_url: str | None
    watch_percentage: int
    is_completed: bool


class ChapterDetailResponse(BaseModel):
    id: UUID
    title: str
    lessons: list[LessonSummary]
    has_notes: bool
    test_id: UUID | None


class LessonPlayResponse(BaseModel):
    youtube_video_id: str
    title: str
    duration_seconds: int | None
    watch_percentage: int
    resume_at_seconds: int


class LessonAccessDenied(BaseModel):
    detail: str = "subscription_required"
    plan_options: list[str]


class NotesResponse(BaseModel):
    url: str
    expires_in_seconds: int
    title: str
    file_size_bytes: int | None


class CreateLessonRequest(BaseModel):
    chapter_id: UUID
    title: str
    title_ml: str
    youtube_video_id: str
    duration_seconds: int | None = None
    is_free: bool = False
    order_index: int = 0


class LessonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    chapter_id: UUID
    title: str
    title_ml: str
    youtube_video_id: str
    duration_seconds: int | None
    is_free: bool
    is_published: bool
    thumbnail_url: str | None
    order_index: int
