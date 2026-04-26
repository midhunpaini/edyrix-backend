from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.exceptions import NotFoundException
from app.models.progress import Test, TestAttempt
from app.models.user import User
from app.schemas.common import CommonResponse
from app.schemas.progress import (
    LastAttempt,
    QuestionResult,
    SubmitTestRequest,
    SubmitTestResponse,
    TestDetailResponse,
    TestHistoryItem,
    TestQuestion,
    TestSummaryResponse,
)

router = APIRouter(prefix="/tests", tags=["tests"])


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


@router.get("/chapter/{chapter_id}", response_model=CommonResponse[TestSummaryResponse])
async def get_chapter_test(
    chapter_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[TestSummaryResponse]:
    result = await db.execute(
        select(Test).where(Test.chapter_id == chapter_id, Test.is_published.is_(True))
    )
    test = result.scalar_one_or_none()
    if test is None:
        raise NotFoundException("Test not found")

    last_attempt_result = await db.execute(
        select(TestAttempt)
        .where(TestAttempt.user_id == user.id, TestAttempt.test_id == test.id)
        .order_by(TestAttempt.completed_at.desc())
        .limit(1)
    )
    last_attempt = last_attempt_result.scalar_one_or_none()

    return CommonResponse.ok(TestSummaryResponse(
        id=test.id,
        title=test.title,
        duration_minutes=test.duration_minutes,
        total_marks=test.total_marks,
        question_count=len(test.questions),
        last_attempt=LastAttempt(
            score=last_attempt.score,
            percentage=last_attempt.percentage or Decimal(0),
            completed_at=last_attempt.completed_at,
        ) if last_attempt else None,
    ))


@router.get("/{test_id}", response_model=CommonResponse[TestDetailResponse])
async def get_test(
    test_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[TestDetailResponse]:
    result = await db.execute(
        select(Test).where(Test.id == test_id, Test.is_published.is_(True))
    )
    test = result.scalar_one_or_none()
    if test is None:
        raise NotFoundException("Test not found")

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
    result = await db.execute(
        select(Test).where(Test.id == test_id, Test.is_published.is_(True))
    )
    test = result.scalar_one_or_none()
    if test is None:
        raise NotFoundException("Test not found")

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
    await db.commit()

    return CommonResponse.ok(SubmitTestResponse(score=score, total_marks=total, percentage=pct, results=results))
