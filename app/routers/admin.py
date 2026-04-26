import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.dependencies import get_db, require_admin
from app.models.content import Chapter, Lesson, Note, Subject
from app.models.doubt import Doubt
from app.models.progress import Test
from app.models.subscription import Payment, Plan, Subscription
from app.models.user import FreeTrial, User
from app.schemas.admin import (
    AdminDashboardResponse,
    AdminDoubtItem,
    AdminDoubtListResponse,
    AdminStudentItem,
    AdminStudentListResponse,
    ChapterAdminResponse,
    CreateChapterRequest,
    CreateSubjectRequest,
    CreateTestRequest,
    NoteUploadResponse,
    PublishToggleResponse,
    RevenueDataPoint,
    SubjectAdminResponse,
    SubjectChaptersAdminResponse,
    TestAdminResponse,
)
from app.schemas.content import CreateLessonRequest, LessonResponse
from app.schemas.doubt import AnswerDoubtRequest, AnswerDoubtResponse
from app.services import notification_service
from app.services.email_service import send_doubt_answered_email
from app.services.storage_service import upload_bytes

router = APIRouter(prefix="/admin", tags=["admin"])

_ALLOWED_CONTENT_TYPES = {"application/pdf"}
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/dashboard", response_model=AdminDashboardResponse, summary="Admin dashboard stats")
async def dashboard(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> AdminDashboardResponse:
    """Return platform-wide statistics: student counts, MRR, pending doubts, and 30-day revenue."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    thirty_days_ago = now - timedelta(days=30)

    total_students = (
        await db.execute(select(func.count(User.id)).where(User.role == "student"))
    ).scalar() or 0

    active_subs = (
        await db.execute(
            select(func.count(Subscription.id)).where(
                Subscription.status == "active",
                or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
            )
        )
    ).scalar() or 0

    mrr_paise = (
        await db.execute(
            select(func.coalesce(func.sum(Plan.price_paise), 0))
            .join(Subscription, Subscription.plan_id == Plan.id)
            .where(
                Subscription.status == "active",
                or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
                Plan.billing_cycle != "one_time",
            )
        )
    ).scalar() or 0

    new_signups = (
        await db.execute(
            select(func.count(User.id)).where(
                User.role == "student", User.created_at >= today_start
            )
        )
    ).scalar() or 0

    pending_doubts = (
        await db.execute(
            select(func.count(Doubt.id)).where(Doubt.status == "pending")
        )
    ).scalar() or 0

    revenue_result = await db.execute(
        select(
            func.date_trunc("day", Payment.created_at).label("day"),
            func.sum(Payment.amount_paise).label("total"),
        )
        .where(Payment.status == "paid", Payment.created_at >= thirty_days_ago)
        .group_by(func.date_trunc("day", Payment.created_at))
        .order_by(func.date_trunc("day", Payment.created_at))
    )
    revenue_days = [
        RevenueDataPoint(date=row.day.strftime("%Y-%m-%d"), amount_paise=row.total)
        for row in revenue_result.all()
    ]

    return AdminDashboardResponse(
        total_students=total_students,
        active_subscriptions=active_subs,
        mrr_paise=mrr_paise,
        new_signups_today=new_signups,
        pending_doubts=pending_doubts,
        revenue_last_30_days=revenue_days,
    )


# ── Students ──────────────────────────────────────────────────────────────────

@router.get("/students", response_model=AdminStudentListResponse, summary="Paginated student list")
async def list_students(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    class_number: int | None = Query(None),
    subscription_status: Literal["active", "trial", "free"] | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> AdminStudentListResponse:
    """Return a paginated, filterable list of students with their subscription status."""
    now = datetime.now(timezone.utc)
    offset = (page - 1) * limit

    base = select(User).where(User.role == "student")
    if search:
        like = f"%{search}%"
        base = base.where(
            or_(User.name.ilike(like), User.phone.ilike(like), User.email.ilike(like))
        )
    if class_number:
        base = base.where(User.current_class == class_number)

    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar() or 0

    users_result = await db.execute(
        base.order_by(User.created_at.desc()).limit(limit).offset(offset)
    )
    users = users_result.scalars().all()

    if not users:
        return AdminStudentListResponse(total=total, students=[])

    user_ids = [u.id for u in users]

    # Batch-fetch active subscriptions and trials in 2 queries instead of N+1
    active_sub_ids: set[uuid.UUID] = {
        row[0]
        for row in (
            await db.execute(
                select(Subscription.user_id).where(
                    Subscription.user_id.in_(user_ids),
                    Subscription.status == "active",
                    or_(
                        Subscription.expires_at.is_(None),
                        Subscription.expires_at > now,
                    ),
                )
            )
        ).all()
    }

    active_trial_ids: set[uuid.UUID] = {
        row[0]
        for row in (
            await db.execute(
                select(FreeTrial.user_id).where(
                    FreeTrial.user_id.in_(user_ids),
                    FreeTrial.expires_at > now,
                )
            )
        ).all()
    }

    items: list[AdminStudentItem] = []
    for user in users:
        if user.id in active_sub_ids:
            sub_status = "active"
        elif user.id in active_trial_ids:
            sub_status = "trial"
        else:
            sub_status = "free"

        if subscription_status and sub_status != subscription_status:
            continue

        items.append(
            AdminStudentItem(
                id=user.id,
                name=user.name,
                phone=user.phone,
                email=user.email,
                current_class=user.current_class,
                subscription_status=sub_status,
                joined_at=user.created_at,
            )
        )

    return AdminStudentListResponse(total=total, students=items)


# ── Content: Subjects ─────────────────────────────────────────────────────────

@router.post(
    "/subjects",
    response_model=SubjectAdminResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a subject",
)
async def create_subject(
    body: CreateSubjectRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> SubjectAdminResponse:
    """Create a new subject. Returns 409 if the slug is already taken."""
    existing = await db.execute(select(Subject).where(Subject.slug == body.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already exists")

    subject = Subject(
        name=body.name,
        name_ml=body.name_ml,
        slug=body.slug,
        class_number=body.class_number,
        icon=body.icon,
        color=body.color,
        monthly_price_paise=body.monthly_price_paise,
        order_index=body.order_index,
    )
    db.add(subject)
    await db.commit()
    await db.refresh(subject)
    return SubjectAdminResponse.model_validate(subject)


# ── Content: Chapters ─────────────────────────────────────────────────────────

@router.post(
    "/chapters",
    response_model=ChapterAdminResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a chapter",
)
async def create_chapter(
    body: CreateChapterRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> ChapterAdminResponse:
    """Create a chapter under a subject. Returns 404 if the subject does not exist."""
    subject_result = await db.execute(
        select(Subject).where(Subject.id == body.subject_id, Subject.is_active.is_(True))
    )
    if subject_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")

    chapter = Chapter(
        subject_id=body.subject_id,
        chapter_number=body.chapter_number,
        title=body.title,
        title_ml=body.title_ml,
        description=body.description,
        order_index=body.order_index,
    )
    db.add(chapter)
    await db.commit()
    await db.refresh(chapter)
    return ChapterAdminResponse.model_validate(chapter)


@router.patch(
    "/chapters/{chapter_id}/publish",
    response_model=PublishToggleResponse,
    summary="Toggle chapter published state",
)
async def toggle_chapter_publish(
    chapter_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> PublishToggleResponse:
    """Toggle the is_published flag on a chapter."""
    result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = result.scalar_one_or_none()
    if chapter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")
    chapter.is_published = not chapter.is_published
    await db.commit()
    return PublishToggleResponse(id=chapter.id, is_published=chapter.is_published)


# ── Content: Lessons ──────────────────────────────────────────────────────────

@router.post(
    "/lessons",
    response_model=LessonResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a lesson",
)
async def create_lesson(
    body: CreateLessonRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> LessonResponse:
    """Create a lesson under a chapter."""
    chapter_result = await db.execute(
        select(Chapter).where(Chapter.id == body.chapter_id)
    )
    if chapter_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")

    lesson = Lesson(
        chapter_id=body.chapter_id,
        title=body.title,
        title_ml=body.title_ml,
        youtube_video_id=body.youtube_video_id,
        duration_seconds=body.duration_seconds,
        is_free=body.is_free,
        order_index=body.order_index,
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)
    return LessonResponse.model_validate(lesson)


@router.patch(
    "/lessons/{lesson_id}/publish",
    response_model=PublishToggleResponse,
    summary="Toggle lesson published state",
)
async def toggle_lesson_publish(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> PublishToggleResponse:
    """Toggle the is_published flag on a lesson."""
    result = await db.execute(select(Lesson).where(Lesson.id == lesson_id))
    lesson = result.scalar_one_or_none()
    if lesson is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found")
    lesson.is_published = not lesson.is_published
    await db.commit()
    return PublishToggleResponse(id=lesson.id, is_published=lesson.is_published)


# ── Content: Tests ────────────────────────────────────────────────────────────

@router.post(
    "/tests",
    response_model=TestAdminResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a chapter test",
)
async def create_test(
    body: CreateTestRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> TestAdminResponse:
    """Create a test with validated MCQ questions. Returns 409 if a test already exists for the chapter."""
    chapter_result = await db.execute(
        select(Chapter).where(Chapter.id == body.chapter_id)
    )
    if chapter_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")

    existing_test = await db.execute(
        select(Test).where(Test.chapter_id == body.chapter_id)
    )
    if existing_test.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Test already exists for this chapter",
        )

    test = Test(
        chapter_id=body.chapter_id,
        title=body.title,
        duration_minutes=body.duration_minutes,
        total_marks=body.total_marks,
        questions=[q.model_dump() for q in body.questions],
    )
    db.add(test)
    await db.commit()
    await db.refresh(test)
    return TestAdminResponse.model_validate(test)


@router.patch(
    "/tests/{test_id}/publish",
    response_model=PublishToggleResponse,
    summary="Toggle test published state",
)
async def toggle_test_publish(
    test_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> PublishToggleResponse:
    """Toggle the is_published flag on a test."""
    result = await db.execute(select(Test).where(Test.id == test_id))
    test = result.scalar_one_or_none()
    if test is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found")
    test.is_published = not test.is_published
    await db.commit()
    return PublishToggleResponse(id=test.id, is_published=test.is_published)


# ── Notes Upload ──────────────────────────────────────────────────────────────

@router.post(
    "/notes/upload",
    response_model=NoteUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload chapter PDF notes",
)
async def upload_note(
    chapter_id: uuid.UUID = Query(...),
    title: str = Query(...),
    file: UploadFile = ...,
    is_premium: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> NoteUploadResponse:
    """Upload a PDF file to R2 and attach it to a chapter. Maximum 20 MB."""
    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF files are allowed"
        )

    chapter_result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    if chapter_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")

    pdf_bytes = await file.read()
    if len(pdf_bytes) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="File exceeds 20 MB limit"
        )

    r2_key = f"notes/{uuid.uuid4()}.pdf"
    await upload_bytes(pdf_bytes, r2_key, content_type="application/pdf")

    note = Note(
        chapter_id=chapter_id,
        title=title,
        r2_key=r2_key,
        file_size_bytes=len(pdf_bytes),
        is_premium=is_premium,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)

    return NoteUploadResponse(id=note.id, r2_key=note.r2_key, file_size_bytes=note.file_size_bytes)


# ── Doubts ────────────────────────────────────────────────────────────────────

@router.get("/doubts", response_model=AdminDoubtListResponse, summary="List all doubts")
async def list_doubts(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Literal["pending", "answered"] | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> AdminDoubtListResponse:
    """Return paginated doubts, optionally filtered by status. Student names are fetched via JOIN."""
    offset = (page - 1) * limit
    StudentUser = aliased(User)

    count_q = select(func.count(Doubt.id))
    fetch_q = (
        select(Doubt, StudentUser)
        .outerjoin(StudentUser, Doubt.user_id == StudentUser.id)
        .order_by(Doubt.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status_filter:
        count_q = count_q.where(Doubt.status == status_filter)
        fetch_q = fetch_q.where(Doubt.status == status_filter)

    total = (await db.execute(count_q)).scalar() or 0
    doubts_result = await db.execute(fetch_q)

    items = [
        AdminDoubtItem(
            id=d.id,
            student_name=student.name if student else "Unknown",
            question_text=d.question_text,
            chapter_id=d.chapter_id,
            lesson_id=d.lesson_id,
            status=d.status,
            created_at=d.created_at,
        )
        for d, student in doubts_result.all()
    ]

    return AdminDoubtListResponse(total=total, doubts=items)


@router.put(
    "/doubts/{doubt_id}/answer",
    response_model=AnswerDoubtResponse,
    summary="Answer a student doubt",
)
async def answer_doubt(
    doubt_id: uuid.UUID,
    body: AnswerDoubtRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> AnswerDoubtResponse:
    """Record an answer to a doubt and notify the student via FCM and email."""
    result = await db.execute(select(Doubt).where(Doubt.id == doubt_id))
    doubt = result.scalar_one_or_none()
    if doubt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Doubt not found")

    doubt.answer_text = body.answer_text
    doubt.answered_by = admin.id
    doubt.answered_at = datetime.now(timezone.utc)
    doubt.status = "answered"
    await db.commit()
    await db.refresh(doubt)

    student_result = await db.execute(select(User).where(User.id == doubt.user_id))
    student = student_result.scalar_one_or_none()

    notif_sent = await notification_service.send_doubt_answered(
        db, doubt.user_id, doubt.question_text  # type: ignore[arg-type]
    )
    if student and student.email:
        await send_doubt_answered_email(student.email, doubt.question_text, body.answer_text)

    return AnswerDoubtResponse(message="Doubt answered", notification_sent=notif_sent)


# ── Admin read endpoints (return admin-shaped data including drafts) ───────────

@router.get(
    "/subjects/{subject_id}",
    response_model=SubjectChaptersAdminResponse,
    summary="Get subject with all chapters (admin)",
)
async def get_subject_with_chapters(
    subject_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> SubjectChaptersAdminResponse:
    """Return a subject and all its chapters (including unpublished) for the admin panel."""
    subject_result = await db.execute(select(Subject).where(Subject.id == subject_id))
    subject = subject_result.scalar_one_or_none()
    if subject is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")

    chapters_result = await db.execute(
        select(Chapter)
        .where(Chapter.subject_id == subject_id)
        .order_by(Chapter.order_index)
    )
    chapters = chapters_result.scalars().all()

    return SubjectChaptersAdminResponse(
        id=subject.id,
        name=subject.name,
        chapters=[ChapterAdminResponse.model_validate(ch) for ch in chapters],
    )


@router.get(
    "/chapters/{chapter_id}/lessons",
    response_model=list[LessonResponse],
    summary="Get all lessons in a chapter (admin)",
)
async def list_chapter_lessons(
    chapter_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[LessonResponse]:
    """Return all lessons for a chapter (including unpublished) for the admin panel."""
    chapter_result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    if chapter_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")

    lessons_result = await db.execute(
        select(Lesson).where(Lesson.chapter_id == chapter_id).order_by(Lesson.order_index)
    )
    return [LessonResponse.model_validate(lesson) for lesson in lessons_result.scalars().all()]


@router.get(
    "/tests/chapter/{chapter_id}",
    response_model=TestAdminResponse,
    summary="Get chapter test (admin)",
)
async def get_chapter_test_admin(
    chapter_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> TestAdminResponse:
    """Return the test for a chapter (including unpublished) for the admin panel."""
    result = await db.execute(select(Test).where(Test.chapter_id == chapter_id))
    test = result.scalar_one_or_none()
    if test is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found")
    return TestAdminResponse.model_validate(test)
