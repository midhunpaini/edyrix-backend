import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.subscription import Plan
from app.schemas.subscription import PlanResponse

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("", response_model=list[PlanResponse])
async def list_plans(db: AsyncSession = Depends(get_db)) -> list[PlanResponse]:
    result = await db.execute(
        select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.order_index)
    )
    plans = result.scalars().all()
    return [PlanResponse.model_validate(p) for p in plans]


@router.get("/{plan_id}", response_model=PlanResponse)
async def get_plan(plan_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> PlanResponse:
    plan = await db.get(Plan, plan_id)
    if plan is None or not plan.is_active:
        raise HTTPException(status_code=404, detail="Plan not found")
    return PlanResponse.model_validate(plan)
