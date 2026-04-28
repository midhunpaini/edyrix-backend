import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query, UploadFile, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.dependencies import get_db, require_admin
from app.exceptions import BadRequestException, ConflictException, NotFoundException
from app.queue import enqueue
from app.models.admin import AdminUser
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
    BulkCreateLessonsRequest,
    BulkCreateLessonsResponse,
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
    UpdateTestRequest,
)
from app.schemas.common import CommonResponse
from app.schemas.content import CreateLessonRequest, LessonResponse, UpdateLessonRequest
from app.schemas.doubt import AnswerDoubtRequest, AnswerDoubtResponse
from app.services.storage_service import upload_bytes

router = APIRouter(prefix="/admin", tags=["admin"])

_ALLOWED_CONTENT_TYPES = {"application/pdf"}
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/dashboard", response_model=CommonResponse[AdminDashboardResponse])
async def dashboard(
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[AdminDashboardResponse]:
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

    revenue_day = func.date(Payment.created_at).label("day")
    revenue_result = await db.execute(
        select(
            revenue_day,
            func.sum(Payment.amount_paise).label("total"),
        )
        .where(Payment.status == "success", Payment.created_at >= thirty_days_ago)
        .group_by(revenue_day)
        .order_by(revenue_day)
    )
    revenue_days = [
        RevenueDataPoint(date=row.day.strftime("%Y-%m-%d"), amount_paise=row.total)
        for row in revenue_result.all()
    ]

    return CommonResponse.ok(AdminDashboardResponse(
        total_students=total_students,
        active_subscriptions=active_subs,
        mrr_paise=mrr_paise,
        new_signups_today=new_signups,
        pending_doubts=pending_doubts,
        revenue_last_30_days=revenue_days,
    ))


# ── Students ──────────────────────────────────────────────────────────────────

@router.get("/students", response_model=CommonResponse[AdminStudentListResponse])
async def list_students(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    class_number: int | None = Query(None),
    subscription_status: Literal["active", "trial", "free"] | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[AdminStudentListResponse]:
    now = datetime.now(timezone.utc)
    offset = (page - 1) * limit

    # Build a subquery for active subscription user IDs.
    active_sub_sq = (
        select(Subscription.user_id)
        .where(
            Subscription.status == "active",
            or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
        )
        .distinct()
        .subquery()
    )
    # Build a subquery for active trial user IDs (no active subscription).
    active_trial_sq = (
        select(FreeTrial.user_id)
        .where(FreeTrial.expires_at > now)
        .where(~FreeTrial.user_id.in_(select(active_sub_sq.c.user_id)))
        .distinct()
        .subquery()
    )

    base = select(User).where(User.role == "student")
    if search:
        like = f"%{search}%"
        base = base.where(
            or_(User.name.ilike(like), User.phone.ilike(like), User.email.ilike(like))
        )
    if class_number:
        base = base.where(User.current_class == class_number)
    if subscription_status == "active":
        base = base.where(User.id.in_(select(active_sub_sq.c.user_id)))
    elif subscription_status == "trial":
        base = base.where(User.id.in_(select(active_trial_sq.c.user_id)))
    elif subscription_status == "free":
        base = base.where(
            ~User.id.in_(select(active_sub_sq.c.user_id)),
            ~User.id.in_(select(active_trial_sq.c.user_id)),
        )

    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar() or 0

    users_result = await db.execute(
        base.order_by(User.created_at.desc()).limit(limit).offset(offset)
    )
    users = users_result.scalars().all()

    if not users:
        return CommonResponse.ok(AdminStudentListResponse(total=total, students=[]))

    user_ids = [u.id for u in users]

    active_sub_ids: set[uuid.UUID] = {
        row[0]
        for row in (
            await db.execute(
                select(Subscription.user_id).where(
                    Subscription.user_id.in_(user_ids),
                    Subscription.status == "active",
                    or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
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

    items: list[AdminStudentItem] = [
        AdminStudentItem(
            id=user.id,
            name=user.name,
            phone=user.phone,
            email=user.email,
            current_class=user.current_class,
            subscription_status=(
                "active" if user.id in active_sub_ids
                else "trial" if user.id in active_trial_ids
                else "free"
            ),
            joined_at=user.created_at,
        )
        for user in users
    ]

    return CommonResponse.ok(AdminStudentListResponse(total=total, students=items))


# ── Content: Subjects ─────────────────────────────────────────────────────────

@router.post("/subjects", response_model=CommonResponse[SubjectAdminResponse], status_code=status.HTTP_201_CREATED)
async def create_subject(
    body: CreateSubjectRequest,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[SubjectAdminResponse]:
    existing = await db.execute(select(Subject).where(Subject.slug == body.slug))
    if existing.scalar_one_or_none():
        raise ConflictException("Slug already exists")

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
    return CommonResponse.ok(SubjectAdminResponse.model_validate(subject), "Subject created")


# ── Content: Chapters ─────────────────────────────────────────────────────────

@router.post("/chapters", response_model=CommonResponse[ChapterAdminResponse], status_code=status.HTTP_201_CREATED)
async def create_chapter(
    body: CreateChapterRequest,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[ChapterAdminResponse]:
    subject_result = await db.execute(
        select(Subject).where(Subject.id == body.subject_id, Subject.is_active.is_(True))
    )
    if subject_result.scalar_one_or_none() is None:
        raise NotFoundException("Subject not found")

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
    return CommonResponse.ok(ChapterAdminResponse.model_validate(chapter), "Chapter created")


@router.patch("/chapters/{chapter_id}/publish", response_model=CommonResponse[PublishToggleResponse])
async def toggle_chapter_publish(
    chapter_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[PublishToggleResponse]:
    result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = result.scalar_one_or_none()
    if chapter is None:
        raise NotFoundException("Chapter not found")
    chapter.is_published = not chapter.is_published
    await db.commit()
    return CommonResponse.ok(PublishToggleResponse(id=chapter.id, is_published=chapter.is_published))


# ── Content: Lessons ──────────────────────────────────────────────────────────

@router.post("/lessons/bulk", response_model=CommonResponse[BulkCreateLessonsResponse], status_code=status.HTTP_201_CREATED)
async def bulk_create_lessons(
    body: BulkCreateLessonsRequest,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[BulkCreateLessonsResponse]:
    chapter_result = await db.execute(select(Chapter).where(Chapter.id == body.chapter_id))
    if chapter_result.scalar_one_or_none() is None:
        raise NotFoundException("Chapter not found")

    created = 0
    errors: list[str] = []
    for i, item in enumerate(body.lessons, start=1):
        try:
            lesson = Lesson(
                chapter_id=body.chapter_id,
                title=item.title,
                title_ml=item.title_ml,
                youtube_video_id=item.youtube_video_id,
                duration_seconds=item.duration_seconds,
                is_free=item.is_free,
                order_index=item.order_index,
            )
            db.add(lesson)
            created += 1
        except Exception as exc:
            errors.append(f"Row {i} ({item.title!r}): {exc}")

    await db.commit()
    return CommonResponse.ok(
        BulkCreateLessonsResponse(created=created, errors=errors),
        f"{created} lesson(s) created",
    )


@router.post("/lessons", response_model=CommonResponse[LessonResponse], status_code=status.HTTP_201_CREATED)
async def create_lesson(
    body: CreateLessonRequest,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[LessonResponse]:
    chapter_result = await db.execute(
        select(Chapter).where(Chapter.id == body.chapter_id)
    )
    if chapter_result.scalar_one_or_none() is None:
        raise NotFoundException("Chapter not found")

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
    return CommonResponse.ok(LessonResponse.model_validate(lesson), "Lesson created")


@router.put("/lessons/{lesson_id}", response_model=CommonResponse[LessonResponse])
async def update_lesson(
    lesson_id: uuid.UUID,
    body: UpdateLessonRequest,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[LessonResponse]:
    result = await db.execute(select(Lesson).where(Lesson.id == lesson_id))
    lesson = result.scalar_one_or_none()
    if lesson is None:
        raise NotFoundException("Lesson not found")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(lesson, field, val)
    await db.commit()
    await db.refresh(lesson)
    return CommonResponse.ok(LessonResponse.model_validate(lesson))


@router.delete("/lessons/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lesson(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> None:
    result = await db.execute(select(Lesson).where(Lesson.id == lesson_id))
    lesson = result.scalar_one_or_none()
    if lesson is None:
        raise NotFoundException("Lesson not found")
    await db.delete(lesson)
    await db.commit()


@router.patch("/lessons/{lesson_id}/publish", response_model=CommonResponse[PublishToggleResponse])
async def toggle_lesson_publish(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[PublishToggleResponse]:
    result = await db.execute(select(Lesson).where(Lesson.id == lesson_id))
    lesson = result.scalar_one_or_none()
    if lesson is None:
        raise NotFoundException("Lesson not found")
    lesson.is_published = not lesson.is_published
    await db.commit()
    return CommonResponse.ok(PublishToggleResponse(id=lesson.id, is_published=lesson.is_published))


# ── Content: Tests ────────────────────────────────────────────────────────────

@router.post("/tests", response_model=CommonResponse[TestAdminResponse], status_code=status.HTTP_201_CREATED)
async def create_test(
    body: CreateTestRequest,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[TestAdminResponse]:
    chapter_result = await db.execute(select(Chapter).where(Chapter.id == body.chapter_id))
    chapter = chapter_result.scalar_one_or_none()
    if chapter is None:
        raise NotFoundException("Chapter not found")

    if body.lesson_id is not None:
        lesson_result = await db.execute(
            select(Lesson).where(Lesson.id == body.lesson_id, Lesson.chapter_id == body.chapter_id)
        )
        if lesson_result.scalar_one_or_none() is None:
            raise NotFoundException("Lesson not found for this chapter")

        existing_test = await db.execute(select(Test).where(Test.lesson_id == body.lesson_id))
        if existing_test.scalar_one_or_none():
            raise ConflictException("Test already exists for this lesson")

    test = Test(
        subject_id=chapter.subject_id,
        chapter_id=body.chapter_id,
        lesson_id=body.lesson_id,
        title=body.title,
        duration_minutes=body.duration_minutes,
        total_marks=body.total_marks,
        questions=[q.model_dump() for q in body.questions],
    )
    db.add(test)
    await db.commit()
    await db.refresh(test)
    return CommonResponse.ok(TestAdminResponse.model_validate(test), "Test created")


@router.put("/tests/{test_id}", response_model=CommonResponse[TestAdminResponse])
async def update_test(
    test_id: uuid.UUID,
    body: UpdateTestRequest,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[TestAdminResponse]:
    result = await db.execute(select(Test).where(Test.id == test_id))
    test = result.scalar_one_or_none()
    if test is None:
        raise NotFoundException("Test not found")
    if body.title is not None:
        test.title = body.title
    if body.duration_minutes is not None:
        test.duration_minutes = body.duration_minutes
    if body.total_marks is not None:
        test.total_marks = body.total_marks
    if body.questions is not None:
        test.questions = [q.model_dump() for q in body.questions]
    await db.commit()
    await db.refresh(test)
    return CommonResponse.ok(TestAdminResponse.model_validate(test))


@router.patch("/tests/{test_id}/publish", response_model=CommonResponse[PublishToggleResponse])
async def toggle_test_publish(
    test_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[PublishToggleResponse]:
    result = await db.execute(select(Test).where(Test.id == test_id))
    test = result.scalar_one_or_none()
    if test is None:
        raise NotFoundException("Test not found")
    test.is_published = not test.is_published
    await db.commit()
    return CommonResponse.ok(PublishToggleResponse(id=test.id, is_published=test.is_published))


# ── Notes Upload ──────────────────────────────────────────────────────────────

@router.post("/notes/upload", response_model=CommonResponse[NoteUploadResponse], status_code=status.HTTP_201_CREATED)
async def upload_note(
    chapter_id: uuid.UUID = Query(...),
    title: str = Query(...),
    file: UploadFile = ...,
    is_premium: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[NoteUploadResponse]:
    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        raise BadRequestException("Only PDF files are allowed")

    chapter_result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    if chapter_result.scalar_one_or_none() is None:
        raise NotFoundException("Chapter not found")

    pdf_bytes = await file.read()
    if len(pdf_bytes) > _MAX_UPLOAD_BYTES:
        raise BadRequestException("File exceeds 20 MB limit")

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

    return CommonResponse.ok(NoteUploadResponse(id=note.id, r2_key=note.r2_key, file_size_bytes=note.file_size_bytes), "Notes uploaded")


# ── Doubts ────────────────────────────────────────────────────────────────────

@router.get("/doubts", response_model=CommonResponse[AdminDoubtListResponse])
async def list_doubts(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Literal["pending", "answered"] | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[AdminDoubtListResponse]:
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

    return CommonResponse.ok(AdminDoubtListResponse(total=total, doubts=items))


@router.put("/doubts/{doubt_id}/answer", response_model=CommonResponse[AnswerDoubtResponse])
async def answer_doubt(
    doubt_id: uuid.UUID,
    body: AnswerDoubtRequest,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
) -> CommonResponse[AnswerDoubtResponse]:
    result = await db.execute(select(Doubt).where(Doubt.id == doubt_id))
    doubt = result.scalar_one_or_none()
    if doubt is None:
        raise NotFoundException("Doubt not found")

    doubt.answer_text = body.answer_text
    doubt.answered_by_admin_id = admin.id
    doubt.answered_at = datetime.now(timezone.utc)
    doubt.status = "answered"
    await db.commit()
    await db.refresh(doubt)

    student_result = await db.execute(select(User).where(User.id == doubt.user_id))
    student = student_result.scalar_one_or_none()

    await enqueue(
        "task_send_doubt_answered",
        user_id=str(doubt.user_id),
        email=student.email if student else None,
        question=doubt.question_text,
        answer=body.answer_text,
    )

    return CommonResponse.ok(AnswerDoubtResponse(message="Doubt answered", notification_sent=True))


# ── Admin read endpoints ───────────────────────────────────────────────────────

@router.get("/subjects/{subject_id}", response_model=CommonResponse[SubjectChaptersAdminResponse])
async def get_subject_with_chapters(
    subject_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[SubjectChaptersAdminResponse]:
    subject_result = await db.execute(select(Subject).where(Subject.id == subject_id))
    subject = subject_result.scalar_one_or_none()
    if subject is None:
        raise NotFoundException("Subject not found")

    chapters_result = await db.execute(
        select(Chapter)
        .where(Chapter.subject_id == subject_id)
        .order_by(Chapter.order_index)
    )
    chapters = chapters_result.scalars().all()

    return CommonResponse.ok(SubjectChaptersAdminResponse(
        id=subject.id,
        name=subject.name,
        chapters=[ChapterAdminResponse.model_validate(ch) for ch in chapters],
    ))


@router.get("/chapters/{chapter_id}/lessons", response_model=CommonResponse[list[LessonResponse]])
async def list_chapter_lessons(
    chapter_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[list[LessonResponse]]:
    chapter_result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    if chapter_result.scalar_one_or_none() is None:
        raise NotFoundException("Chapter not found")

    lessons_result = await db.execute(
        select(Lesson).where(Lesson.chapter_id == chapter_id).order_by(Lesson.order_index)
    )
    return CommonResponse.ok([LessonResponse.model_validate(lesson) for lesson in lessons_result.scalars().all()])


@router.get("/tests/chapter/{chapter_id}", response_model=CommonResponse[TestAdminResponse])
async def get_chapter_test_admin(
    chapter_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[TestAdminResponse]:
    result = await db.execute(
        select(Test).where(Test.chapter_id == chapter_id).order_by(Test.created_at, Test.id).limit(1)
    )
    test = result.scalar_one_or_none()
    if test is None:
        raise NotFoundException("Test not found")
    return CommonResponse.ok(TestAdminResponse.model_validate(test))
