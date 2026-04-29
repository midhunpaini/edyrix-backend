import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_admin
from app.exceptions import ConflictException, NotFoundException
from app.models.admin import AdminUser
from app.models.content import Chapter, Lesson, Subject
from app.models.progress import Test, TestAttempt
from app.schemas.admin import (
    CreateTestRequest,
    PublishToggleResponse,
    TestAdminResponse,
    TestAnalyticsResponse,
    TestListItem,
    UpdateTestRequest,
)
from app.schemas.common import CommonResponse
from app.services import analytics_service
from app.utils.audit import log_audit

router = APIRouter(prefix="/tests", tags=["admin:tests"])


@router.get("", response_model=CommonResponse[list[TestListItem]])
async def list_all_tests(
    subject_id: uuid.UUID | None = Query(None),
    chapter_id: uuid.UUID | None = Query(None),
    is_published: bool | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[list[TestListItem]]:
    q = (
        select(
            Test.id,
            Test.title,
            Test.chapter_id,
            Chapter.title.label("chapter_title"),
            Subject.name.label("subject_name"),
            Test.questions,
            Test.is_published,
            func.count(TestAttempt.id).label("attempt_count"),
            func.coalesce(func.avg(TestAttempt.percentage), 0).label("avg_score_pct"),
        )
        .join(Chapter, Test.chapter_id == Chapter.id)
        .join(Subject, Test.subject_id == Subject.id)
        .outerjoin(TestAttempt, TestAttempt.test_id == Test.id)
        .group_by(Test.id, Test.title, Test.chapter_id, Chapter.title, Subject.name, Test.questions, Test.is_published)
        .order_by(Subject.name, Chapter.title, Test.created_at)
    )
    if subject_id:
        q = q.where(Test.subject_id == subject_id)
    if chapter_id:
        q = q.where(Test.chapter_id == chapter_id)
    if is_published is not None:
        q = q.where(Test.is_published == is_published)

    rows = (await db.execute(q)).all()
    items = [
        TestListItem(
            id=r[0], title=r[1], chapter_id=r[2], chapter_title=r[3], subject_name=r[4],
            question_count=len(r[5]) if r[5] else 0,
            is_published=r[6],
            attempt_count=r[7],
            avg_score_pct=round(float(r[8]), 1),
        )
        for r in rows
    ]
    return CommonResponse.ok(items)


@router.get("/chapter/{chapter_id}", response_model=CommonResponse[TestAdminResponse])
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


@router.get("/{test_id}/analytics", response_model=CommonResponse[TestAnalyticsResponse])
async def get_test_analytics(
    test_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[TestAnalyticsResponse]:
    test = (await db.execute(select(Test).where(Test.id == test_id))).scalar_one_or_none()
    if test is None:
        raise NotFoundException("Test not found")

    attempts_result = await db.execute(
        select(TestAttempt.answers, TestAttempt.score, TestAttempt.total_marks, TestAttempt.percentage)
        .where(TestAttempt.test_id == test_id)
    )
    result = analytics_service.compute_test_analytics(test, attempts_result.all())
    return CommonResponse.ok(TestAnalyticsResponse(**result))


@router.post("/{test_id}/duplicate", response_model=CommonResponse[dict], status_code=status.HTTP_201_CREATED)
async def duplicate_test(
    test_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
) -> CommonResponse[dict]:
    test = (await db.execute(select(Test).where(Test.id == test_id))).scalar_one_or_none()
    if test is None:
        raise NotFoundException("Test not found")
    copy = Test(
        subject_id=test.subject_id,
        chapter_id=test.chapter_id,
        lesson_id=test.lesson_id,
        title=f"{test.title} (Copy)",
        duration_minutes=test.duration_minutes,
        total_marks=test.total_marks,
        questions=test.questions,
        is_published=False,
    )
    db.add(copy)
    await log_audit(db, admin.id, "test.duplicate", "test", test_id, {"new_title": copy.title}, request)
    await db.commit()
    await db.refresh(copy)
    return CommonResponse.ok({"new_test_id": str(copy.id)})


@router.post("", response_model=CommonResponse[TestAdminResponse], status_code=status.HTTP_201_CREATED)
async def create_test(
    body: CreateTestRequest,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[TestAdminResponse]:
    chapter = (await db.execute(select(Chapter).where(Chapter.id == body.chapter_id))).scalar_one_or_none()
    if chapter is None:
        raise NotFoundException("Chapter not found")
    if body.lesson_id is not None:
        if (await db.execute(select(Lesson).where(Lesson.id == body.lesson_id, Lesson.chapter_id == body.chapter_id))).scalar_one_or_none() is None:
            raise NotFoundException("Lesson not found for this chapter")
        if (await db.execute(select(Test).where(Test.lesson_id == body.lesson_id))).scalar_one_or_none():
            raise ConflictException("Test already exists for this lesson")
    test = Test(
        subject_id=chapter.subject_id, chapter_id=body.chapter_id, lesson_id=body.lesson_id,
        title=body.title, duration_minutes=body.duration_minutes, total_marks=body.total_marks,
        questions=[q.model_dump() for q in body.questions],
    )
    db.add(test)
    await db.commit()
    await db.refresh(test)
    return CommonResponse.ok(TestAdminResponse.model_validate(test), "Test created")


@router.put("/{test_id}", response_model=CommonResponse[TestAdminResponse])
async def update_test(
    test_id: uuid.UUID,
    body: UpdateTestRequest,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[TestAdminResponse]:
    test = (await db.execute(select(Test).where(Test.id == test_id))).scalar_one_or_none()
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


@router.patch("/{test_id}/publish", response_model=CommonResponse[PublishToggleResponse])
async def toggle_test_publish(
    test_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[PublishToggleResponse]:
    test = (await db.execute(select(Test).where(Test.id == test_id))).scalar_one_or_none()
    if test is None:
        raise NotFoundException("Test not found")
    test.is_published = not test.is_published
    await db.commit()
    return CommonResponse.ok(PublishToggleResponse(id=test.id, is_published=test.is_published))
