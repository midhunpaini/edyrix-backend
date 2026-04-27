from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User, UserGoal
from app.schemas.common import CommonResponse
from app.schemas.user import UserGoalResponse, UserGoalUpdateRequest

router = APIRouter(prefix="/goals", tags=["goals"])


@router.get("/me", response_model=CommonResponse[UserGoalResponse])
async def get_goal(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[UserGoalResponse]:
    result = await db.execute(select(UserGoal).where(UserGoal.user_id == user.id))
    goal = result.scalar_one_or_none()
    if goal is None:
        return CommonResponse.ok(UserGoalResponse(exam_date=None, daily_minutes=30, target_score=70))
    return CommonResponse.ok(UserGoalResponse.model_validate(goal))


@router.put("/me", response_model=CommonResponse[UserGoalResponse])
async def upsert_goal(
    body: UserGoalUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[UserGoalResponse]:
    result = await db.execute(select(UserGoal).where(UserGoal.user_id == user.id))
    goal = result.scalar_one_or_none()

    if goal is None:
        goal = UserGoal(
            user_id=user.id,
            exam_date=body.exam_date,
            daily_minutes=body.daily_minutes if body.daily_minutes is not None else 30,
            target_score=body.target_score if body.target_score is not None else 70,
        )
        db.add(goal)
    else:
        if body.exam_date is not None:
            goal.exam_date = body.exam_date
        if body.daily_minutes is not None:
            goal.daily_minutes = body.daily_minutes
        if body.target_score is not None:
            goal.target_score = body.target_score
        goal.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(goal)
    return CommonResponse.ok(UserGoalResponse.model_validate(goal))
