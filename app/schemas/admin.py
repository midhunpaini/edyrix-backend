import uuid as _uuid
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Subjects ──────────────────────────────────────────────────────────────────

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


# ── Chapters ──────────────────────────────────────────────────────────────────

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


class ReorderItem(BaseModel):
    id: UUID
    order_index: int


class ReorderRequest(BaseModel):
    items: list[ReorderItem]


# ── Tests ─────────────────────────────────────────────────────────────────────

class QuestionInput(BaseModel):
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
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
    lesson_id: UUID | None = None
    title: str
    duration_minutes: int = 30
    total_marks: int
    questions: list[QuestionInput]


class UpdateTestRequest(BaseModel):
    title: str | None = None
    duration_minutes: int | None = None
    total_marks: int | None = None
    questions: list[QuestionInput] | None = None


class TestAdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject_id: UUID
    chapter_id: UUID
    lesson_id: UUID | None
    title: str
    duration_minutes: int
    total_marks: int
    questions: list[dict]
    is_published: bool
    created_at: datetime


class TestListItem(BaseModel):
    id: UUID
    title: str
    chapter_id: UUID
    chapter_title: str
    subject_name: str
    question_count: int
    is_published: bool
    attempt_count: int
    avg_score_pct: float


class TestAnalyticsResponse(BaseModel):
    attempt_count: int
    avg_score_pct: float
    pass_rate: float
    question_analytics: list[dict]


# ── Lessons ───────────────────────────────────────────────────────────────────

class BulkLessonItem(BaseModel):
    title: str
    title_ml: str = ""
    youtube_video_id: str
    duration_seconds: int | None = None
    is_free: bool = False
    order_index: int = 0


class BulkCreateLessonsRequest(BaseModel):
    chapter_id: UUID
    lessons: list[BulkLessonItem]

    @field_validator("lessons")
    @classmethod
    def at_least_one(cls, v: list) -> list:
        if not v:
            raise ValueError("At least one lesson is required")
        return v


class BulkCreateLessonsResponse(BaseModel):
    created: int
    errors: list[str]


class ContentStatsResponse(BaseModel):
    total_views: int
    unique_viewers: int
    avg_completion_pct: float
    completion_rate: float


# ── Notes ─────────────────────────────────────────────────────────────────────

class NoteUploadResponse(BaseModel):
    id: UUID
    r2_key: str
    file_size_bytes: int


class NoteAdminItem(BaseModel):
    id: UUID
    title: str
    r2_key: str
    file_size_bytes: int | None
    presigned_url: str
    created_at: datetime


# ── Dashboard ─────────────────────────────────────────────────────────────────

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
    # extended fields
    trial_users: int = 0
    trial_conversion_rate: float = 0.0
    churn_this_month: int = 0
    churn_rate_pct: float = 0.0
    arr_paise: int = 0
    revenue_by_plan: list[dict] = Field(default_factory=list)
    top_lessons: list[dict] = Field(default_factory=list)
    low_completion_lessons: list[dict] = Field(default_factory=list)
    subject_engagement: list[dict] = Field(default_factory=list)


# ── Students ──────────────────────────────────────────────────────────────────

class AdminStudentItem(BaseModel):
    id: UUID
    name: str
    phone: str | None
    email: str | None
    current_class: int | None
    subscription_status: str
    is_suspended: bool = False
    joined_at: datetime


class AdminStudentListResponse(BaseModel):
    total: int
    students: list[AdminStudentItem]


class StudentDetailResponse(BaseModel):
    id: UUID
    name: str
    phone: str | None
    email: str | None
    avatar_url: str | None
    current_class: int | None
    medium: str
    is_suspended: bool
    suspended_reason: str | None
    subscription_status: str
    joined_at: datetime
    stats: dict
    subject_progress: list[dict]
    payment_history: list[dict]
    recent_activity: list[dict]


class GrantAccessRequest(BaseModel):
    plan_id: UUID
    duration_days: int
    reason: str


class GrantAccessResponse(BaseModel):
    subscription_id: UUID
    expires_at: datetime


class SuspendRequest(BaseModel):
    reason: str


# ── Doubts ────────────────────────────────────────────────────────────────────

class AdminDoubtItem(BaseModel):
    id: UUID
    student_name: str
    student_class: int | None = None
    subject_name: str | None = None
    chapter_title: str | None = None
    question_text: str
    chapter_id: UUID | None
    lesson_id: UUID | None
    status: str
    assigned_to_id: UUID | None = None
    assigned_to_name: str | None = None
    hours_pending: float | None = None
    sla_breached: bool = False
    image_url: str | None = None
    created_at: datetime


class AdminDoubtListResponse(BaseModel):
    total: int
    doubts: list[AdminDoubtItem]


class DoubtStatsResponse(BaseModel):
    pending_count: int
    avg_response_hours: float
    answered_today: int
    oldest_pending_hours: float
    sla_breached_count: int
    by_subject: list[dict]


class AssignDoubtRequest(BaseModel):
    teacher_id: UUID


class CloseDoubtRequest(BaseModel):
    reason: str


class BulkCloseRequest(BaseModel):
    doubt_ids: list[UUID]
    reason: str


class DoubtTemplateCreate(BaseModel):
    title: str
    body: str
    subject_id: UUID | None = None


class DoubtTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    body: str
    subject_id: UUID | None
    created_at: datetime


# ── Notifications ─────────────────────────────────────────────────────────────

class SendNotificationRequest(BaseModel):
    title: str
    body: str
    target_segment: str
    data: dict = Field(default_factory=dict)
    scheduled_at: datetime | None = None


class SendNotificationResponse(BaseModel):
    log_id: UUID
    target_count: int
    sent_count: int
    failed_count: int


class NotificationLogItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    target_segment: str
    target_count: int
    sent_count: int
    failed_count: int
    status: str
    sent_at: datetime | None
    created_at: datetime


# ── Revenue ───────────────────────────────────────────────────────────────────

class RevenueResponse(BaseModel):
    total_revenue_paise: int
    successful_payments: int
    failed_payments: int
    refunded_paise: int
    net_revenue_paise: int
    daily_breakdown: list[dict]
    plan_breakdown: list[dict]


class RevenueForecastResponse(BaseModel):
    current_mrr_paise: int
    projected_next_month_paise: int
    subs_expiring_this_month: int
    historical_renewal_rate: float
    projected_renewals: int
    at_risk_revenue_paise: int


class SubscriptionListItem(BaseModel):
    id: UUID
    student_name: str
    student_phone: str | None
    plan_name: str
    amount_paise: int
    started_at: datetime
    expires_at: datetime | None
    status: str
    payment_id: UUID | None


class SubscriptionListResponse(BaseModel):
    total: int
    subscriptions: list[SubscriptionListItem]


class RefundResponse(BaseModel):
    refund_id: str
    status: str


# ── Settings ─────────────────────────────────────────────────────────────────

class FeatureFlagUpdateRequest(BaseModel):
    flag_name: str
    value: bool | int | str


class AuditLogItem(BaseModel):
    id: UUID
    admin_name: str | None
    action: str
    resource_type: str | None
    resource_id: UUID | None
    changes: dict
    ip_address: str | None
    created_at: datetime


class AuditLogListResponse(BaseModel):
    total: int
    logs: list[AuditLogItem]


class SettingsResponse(BaseModel):
    plans: list[dict]
    feature_flags: dict
    admin_users: list[dict]


# ── Subjects with chapters ───────────────────────────────────────────────────

class SubjectChaptersAdminResponse(BaseModel):
    id: UUID
    name: str
    chapters: list[ChapterAdminResponse]
