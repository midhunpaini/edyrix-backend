from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.exceptions import NotFoundException
from app.models.content import Chapter, Lesson, Subject
from app.models.progress import Test, TestAttempt, WatchHistory
from app.models.user import User
from app.schemas.common import CommonResponse
from app.schemas.progress import (
    AvailableTestItem,
    LastAttempt,
    QuestionResult,
    SubmitTestRequest,
    SubmitTestResponse,
    TestDetailResponse,
    TestHistoryItem,
    TestQuestion,
    TestSummaryResponse,
)
from app.services.trajectory_service import update_trajectory
from app.utils.access_control import user_has_access

router = APIRouter(prefix="/tests", tags=["tests"])


def _last_attempt_response(attempt: TestAttempt | None) -> LastAttempt | None:
    if attempt is None:
        return None
    return LastAttempt(
        score=attempt.score,
        total_marks=attempt.total_marks,
        percentage=attempt.percentage or Decimal(0),
        completed_at=attempt.completed_at,
    )


async def _last_attempt_map(
    db: AsyncSession,
    user: User,
    test_ids: list[UUID],
) -> dict[UUID, TestAttempt]:
    if not test_ids:
        return {}
    result = await db.execute(
        select(TestAttempt)
        .where(TestAttempt.user_id == user.id, TestAttempt.test_id.in_(test_ids))
        .order_by(TestAttempt.completed_at.desc())
    )
    attempts: dict[UUID, TestAttempt] = {}
    for attempt in result.scalars().all():
        if attempt.test_id not in attempts:
            attempts[attempt.test_id] = attempt
    return attempts


async def _unlock_state(
    db: AsyncSession,
    user: User,
    lesson: Lesson,
    subject: Subject,
) -> tuple[bool, str | None]:
    if not lesson.is_free:
        has_access = await user_has_access(db, user, subject.id, subject.class_number)
        if not has_access:
            return False, "subscription_required"

    result = await db.execute(
        select(WatchHistory).where(
            WatchHistory.user_id == user.id,
            WatchHistory.lesson_id == lesson.id,
            WatchHistory.is_completed.is_(True),
        )
    )
    if result.scalar_one_or_none() is None:
        return False, "complete_lesson"
    return True, None


def _locked_exception(reason: str | None, lesson: Lesson, chapter: Chapter) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "detail": "test_locked",
            "unlock_reason": reason or "complete_lesson",
            "lesson_id": str(lesson.id),
            "lesson_title": lesson.title,
            "chapter_id": str(chapter.id),
            "chapter_title": chapter.title,
        },
    )


async def _test_context_by_id(db: AsyncSession, test_id: UUID):
    result = await db.execute(
        select(Test, Subject, Chapter, Lesson)
        .join(Subject, Test.subject_id == Subject.id)
        .join(Chapter, Test.chapter_id == Chapter.id)
        .join(Lesson, Test.lesson_id == Lesson.id)
        .where(
            Test.id == test_id,
            Test.lesson_id.isnot(None),
            Test.is_published.is_(True),
            Subject.is_active.is_(True),
            Chapter.is_published.is_(True),
            Lesson.is_published.is_(True),
        )
    )
    return result.first()


@router.get("/history", response_model=CommonResponse[list[TestHistoryItem]])
async def get_test_history(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[list[TestHistoryItem]]:
    result = await db.execute(
        select(TestAttempt, Test)
        .join(Test, TestAttempt.test_id == Test.id)
        .where(TestAttempt.user_id == user.id)
        .order_by(TestAttempt.completed_at.desc())
    )
    items = [
        TestHistoryItem(
            attempt_id=attempt.id,
            test_title=test.title,
            score=attempt.score,
            total_marks=attempt.total_marks,
            percentage=attempt.percentage or Decimal(0),
            completed_at=attempt.completed_at,
        )
        for attempt, test in result.all()
    ]
    return CommonResponse.ok(items)


@router.get("/available", response_model=CommonResponse[list[AvailableTestItem]])
async def get_available_tests(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[list[AvailableTestItem]]:
    if user.current_class is None:
        return CommonResponse.ok([])

    result = await db.execute(
        select(Test, Subject, Chapter, Lesson)
        .join(Subject, Test.subject_id == Subject.id)
        .join(Chapter, Test.chapter_id == Chapter.id)
        .join(Lesson, Test.lesson_id == Lesson.id)
        .where(
            Subject.class_number == user.current_class,
            Subject.is_active.is_(True),
            Chapter.is_published.is_(True),
            Lesson.is_published.is_(True),
            Test.lesson_id.isnot(None),
            Test.is_published.is_(True),
        )
        .order_by(Subject.order_index, Chapter.order_index, Lesson.order_index, Test.created_at)
    )
    rows = result.all()
    attempts = await _last_attempt_map(db, user, [test.id for test, *_ in rows])

    items: list[AvailableTestItem] = []
    for test, subject, chapter, lesson in rows:
        is_unlocked, reason = await _unlock_state(db, user, lesson, subject)
        items.append(
            AvailableTestItem(
                id=test.id,
                title=test.title,
                subject_id=subject.id,
                subject_name=subject.name,
                chapter_id=chapter.id,
                chapter_number=chapter.chapter_number,
                chapter_title=chapter.title,
                lesson_id=lesson.id,
                lesson_title=lesson.title,
                duration_minutes=test.duration_minutes,
                total_marks=test.total_marks,
                question_count=len(test.questions),
                is_unlocked=is_unlocked,
                unlock_reason=reason,
                last_attempt=_last_attempt_response(attempts.get(test.id)),
            )
        )
    return CommonResponse.ok(items)


@router.get("/lesson/{lesson_id}", response_model=CommonResponse[TestSummaryResponse])
async def get_lesson_test(
    lesson_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[TestSummaryResponse]:
    result = await db.execute(
        select(Test, Subject, Chapter, Lesson)
        .join(Subject, Test.subject_id == Subject.id)
        .join(Chapter, Test.chapter_id == Chapter.id)
        .join(Lesson, Test.lesson_id == Lesson.id)
        .where(
            Test.lesson_id == lesson_id,
            Test.is_published.is_(True),
            Subject.is_active.is_(True),
            Chapter.is_published.is_(True),
            Lesson.is_published.is_(True),
        )
        .order_by(Test.created_at, Test.id)
        .limit(1)
    )
    row = result.first()
    if row is None:
        raise NotFoundException("Test not found")
    test, subject, chapter, lesson = row
    attempts = await _last_attempt_map(db, user, [test.id])
    is_unlocked, reason = await _unlock_state(db, user, lesson, subject)
    return CommonResponse.ok(TestSummaryResponse(
        id=test.id,
        title=test.title,
        subject_id=subject.id,
        subject_name=subject.name,
        chapter_id=chapter.id,
        chapter_number=chapter.chapter_number,
        chapter_title=chapter.title,
        lesson_id=lesson.id,
        lesson_title=lesson.title,
        duration_minutes=test.duration_minutes,
        total_marks=test.total_marks,
        question_count=len(test.questions),
        is_unlocked=is_unlocked,
        unlock_reason=reason,
        last_attempt=_last_attempt_response(attempts.get(test.id)),
    ))


@router.get("/chapter/{chapter_id}", response_model=CommonResponse[TestSummaryResponse])
async def get_chapter_test(
    chapter_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[TestSummaryResponse]:
    result = await db.execute(
        select(Test, Subject, Chapter, Lesson)
        .join(Subject, Test.subject_id == Subject.id)
        .join(Chapter, Test.chapter_id == Chapter.id)
        .join(Lesson, Test.lesson_id == Lesson.id)
        .where(
            Test.chapter_id == chapter_id,
            Test.lesson_id.isnot(None),
            Test.is_published.is_(True),
        )
        .order_by(Lesson.order_index, Test.created_at, Test.id)
        .limit(1)
    )
    row = result.first()
    if row is None:
        raise NotFoundException("Test not found")
    test, subject, chapter, lesson = row
    attempts = await _last_attempt_map(db, user, [test.id])
    is_unlocked, reason = await _unlock_state(db, user, lesson, subject)

    return CommonResponse.ok(TestSummaryResponse(
        id=test.id,
        title=test.title,
        subject_id=subject.id,
        subject_name=subject.name,
        chapter_id=chapter.id,
        chapter_number=chapter.chapter_number,
        chapter_title=chapter.title,
        lesson_id=lesson.id,
        lesson_title=lesson.title,
        duration_minutes=test.duration_minutes,
        total_marks=test.total_marks,
        question_count=len(test.questions),
        is_unlocked=is_unlocked,
        unlock_reason=reason,
        last_attempt=_last_attempt_response(attempts.get(test.id)),
    ))


@router.get("/{test_id}", response_model=CommonResponse[TestDetailResponse])
async def get_test(
    test_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[TestDetailResponse]:
    row = await _test_context_by_id(db, test_id)
    if row is None:
        raise NotFoundException("Test not found")
    test, subject, chapter, lesson = row

    is_unlocked, reason = await _unlock_state(db, user, lesson, subject)
    if not is_unlocked:
        raise _locked_exception(reason, lesson, chapter)

    questions = [
        TestQuestion(
            id=q["id"],
            text=q["text"],
            text_ml=q.get("text_ml", ""),
            options=q["options"],
            marks=q.get("marks", 1),
        )
        for q in test.questions
    ]
    return CommonResponse.ok(TestDetailResponse(
        id=test.id,
        title=test.title,
        subject_id=subject.id,
        subject_name=subject.name,
        chapter_id=chapter.id,
        chapter_number=chapter.chapter_number,
        chapter_title=chapter.title,
        lesson_id=lesson.id,
        lesson_title=lesson.title,
        duration_minutes=test.duration_minutes,
        total_marks=test.total_marks,
        questions=questions,
    ))


@router.post("/{test_id}/submit", response_model=CommonResponse[SubmitTestResponse])
async def submit_test(
    test_id: UUID,
    body: SubmitTestRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[SubmitTestResponse]:
    row = await _test_context_by_id(db, test_id)
    if row is None:
        raise NotFoundException("Test not found")
    test, subject, chapter, lesson = row

    is_unlocked, reason = await _unlock_state(db, user, lesson, subject)
    if not is_unlocked:
        raise _locked_exception(reason, lesson, chapter)

    score = 0
    results: list[QuestionResult] = []

    for q in test.questions:
        q_id: str = q["id"]
        correct: int = q["correct_answer"]
        given: int = body.answers.get(q_id, -1)
        is_correct = given == correct
        if is_correct:
            score += q.get("marks", 1)
        results.append(
            QuestionResult(
                question_id=q_id,
                your_answer=given,
                correct_answer=correct,
                is_correct=is_correct,
                explanation=q.get("explanation", ""),
            )
        )

    total = test.total_marks
    pct = Decimal(score * 100 / total).quantize(Decimal("0.01")) if total else Decimal(0)

    attempt = TestAttempt(
        user_id=user.id,
        test_id=test.id,
        answers=body.answers,
        score=score,
        total_marks=total,
        percentage=pct,
        time_taken_seconds=body.time_taken_seconds,
    )
    db.add(attempt)
    await update_trajectory(db, user.id, subject.id, pct)
    await db.commit()
    await db.refresh(attempt)

    return CommonResponse.ok(SubmitTestResponse(attempt_id=attempt.id, score=score, total_marks=total, percentage=pct, results=results))


@router.get("/{attempt_id}/share-text", response_model=CommonResponse[dict])
async def get_share_text(
    attempt_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[dict]:
    result = await db.execute(
        select(TestAttempt, Test)
        .join(Test, TestAttempt.test_id == Test.id)
        .where(TestAttempt.id == attempt_id, TestAttempt.user_id == user.id)
    )
    row = result.first()
    if row is None:
        raise NotFoundException("Attempt not found")
    attempt, test = row
    pct = int(attempt.percentage or 0)
    text = (
        f"I scored {pct}% on '{test.title}' on Edyrix! "
        f"({attempt.score}/{attempt.total_marks} marks) 🎯\n"
        f"Study smarter for your SSLC — try Edyrix!"
    )
    import urllib.parse
    wa_url = f"https://wa.me/?text={urllib.parse.quote(text)}"
    return CommonResponse.ok({"text": text, "wa_url": wa_url})
