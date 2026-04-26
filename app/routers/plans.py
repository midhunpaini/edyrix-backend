import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.exceptions import NotFoundException
from app.models.subscription import Plan
from app.schemas.common import CommonResponse
from app.schemas.subscription import PlanResponse

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("", response_model=CommonResponse[list[PlanResponse]])
async def list_plans(db: AsyncSession = Depends(get_db)) -> CommonResponse[list[PlanResponse]]:
    result = await db.execute(
        select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.order_index)
    )
    return CommonResponse.ok([PlanResponse.model_validate(p) for p in result.scalars().all()])


@router.get("/{plan_id}", response_model=CommonResponse[PlanResponse])
async def get_plan(plan_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> CommonResponse[PlanResponse]:
    plan = await db.get(Plan, plan_id)
    if plan is None or not plan.is_active:
        raise NotFoundException("Plan not found")
    return CommonResponse.ok(PlanResponse.model_validate(plan))
