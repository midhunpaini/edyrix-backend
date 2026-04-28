import uuid as _uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
    now = datetime.now(timezone.utc)

    # Atomic upsert prevents a UniqueConstraint violation if two concurrent requests
    # both see no existing row and both attempt to INSERT.
    stmt = pg_insert(UserGoal).values(
        id=_uuid.uuid4(),
        user_id=user.id,
        exam_date=body.exam_date,
        daily_minutes=body.daily_minutes if body.daily_minutes is not None else 30,
        target_score=body.target_score if body.target_score is not None else 70,
        created_at=now,
        updated_at=now,
    )

    update_fields: dict = {"updated_at": now}
    if body.exam_date is not None:
        update_fields["exam_date"] = body.exam_date
    if body.daily_minutes is not None:
        update_fields["daily_minutes"] = body.daily_minutes
    if body.target_score is not None:
        update_fields["target_score"] = body.target_score

    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id"],
        set_=update_fields,
    )
    await db.execute(stmt)
    await db.commit()

    result = await db.execute(select(UserGoal).where(UserGoal.user_id == user.id))
    goal = result.scalar_one()
    return CommonResponse.ok(UserGoalResponse.model_validate(goal))
