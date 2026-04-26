from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.content import Chapter, Lesson, Subject
from app.models.progress import TestAttempt, WatchHistory
from app.models.user import FCMToken, FreeTrial, User
from app.schemas.common import CommonResponse, MessageResponse
from app.schemas.user import FCMTokenRequest, UserResponse, UserStatsResponse, UserUpdateRequest

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=CommonResponse[UserResponse])
async def get_me(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[UserResponse]:
    trial_result = await db.execute(
        select(FreeTrial).where(FreeTrial.user_id == user.id)
    )
    trial = trial_result.scalar_one_or_none()
    data = UserResponse.model_validate(user)
    if trial:
        data.free_trial_expires_at = trial.expires_at
    return CommonResponse.ok(data)


@router.put("/me", response_model=CommonResponse[UserResponse])
async def update_me(
    body: UserUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[UserResponse]:
    if body.name is not None:
        user.name = body.name
    if body.current_class is not None:
        user.current_class = body.current_class
    if body.medium is not None:
        user.medium = body.medium
    user.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)
    return CommonResponse.ok(UserResponse.model_validate(user))


@router.get("/me/stats", response_model=CommonResponse[UserStatsResponse])
async def get_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[UserStatsResponse]:
    completed_result = await db.execute(
        select(func.count(WatchHistory.id)).where(
            WatchHistory.user_id == user.id,
            WatchHistory.is_completed.is_(True),
        )
    )
    videos_completed: int = completed_result.scalar() or 0

    agg_result = await db.execute(
        select(
            func.count(TestAttempt.id),
            func.coalesce(func.avg(TestAttempt.percentage), 0),
        ).where(TestAttempt.user_id == user.id)
    )
    tests_taken_raw, avg_pct_raw = agg_result.first()
    tests_taken: int = tests_taken_raw or 0
    avg_score = round(float(avg_pct_raw or 0), 1)

    active_subjects_result = await db.execute(
        select(Subject.slug)
        .join(Chapter, Chapter.subject_id == Subject.id)
        .join(Lesson, Lesson.chapter_id == Chapter.id)
        .join(WatchHistory, WatchHistory.lesson_id == Lesson.id)
        .where(WatchHistory.user_id == user.id)
        .distinct()
    )
    subjects_active = [row[0] for row in active_subjects_result.all()]

    return CommonResponse.ok(UserStatsResponse(
        videos_completed=videos_completed,
        tests_taken=tests_taken,
        avg_test_score=avg_score,
        streak_days=0,
        subjects_active=subjects_active,
    ))


@router.post("/fcm-token", status_code=status.HTTP_200_OK, response_model=CommonResponse[MessageResponse])
async def register_fcm_token(
    body: FCMTokenRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[MessageResponse]:
    existing = await db.execute(
        select(FCMToken).where(
            FCMToken.user_id == user.id, FCMToken.token == body.token
        )
    )
    if existing.scalar_one_or_none() is None:
        db.add(FCMToken(user_id=user.id, token=body.token, platform=body.platform))
        await db.commit()
    return CommonResponse.ok(MessageResponse(message="Token registered"))
