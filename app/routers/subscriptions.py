from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.subscription import Plan, Subscription
from app.models.user import FreeTrial, User
from app.schemas.common import CommonResponse
from app.schemas.subscription import (
    FreeTrialDetail,
    MySubscriptionResponse,
    PlanResponse,
    SubscriptionDetail,
)

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.get("/my", response_model=CommonResponse[MySubscriptionResponse])
async def get_my_subscription(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[MySubscriptionResponse]:
    now = datetime.now(timezone.utc)

    sub_result = await db.execute(
        select(Subscription, Plan)
        .join(Plan, Subscription.plan_id == Plan.id)
        .where(
            Subscription.user_id == user.id,
            Subscription.status == "active",
            or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
        )
        .order_by(Subscription.started_at.desc())
        .limit(1)
    )
    row = sub_result.first()
    subscription_detail: SubscriptionDetail | None = None
    if row:
        sub, plan = row
        subscription_detail = SubscriptionDetail(
            id=sub.id,
            plan=PlanResponse.model_validate(plan),
            status=sub.status,
            started_at=sub.started_at,
            expires_at=sub.expires_at,
            auto_renew=sub.auto_renew,
        )

    trial_result = await db.execute(
        select(FreeTrial).where(FreeTrial.user_id == user.id)
    )
    trial = trial_result.scalar_one_or_none()
    trial_active = trial is not None and trial.expires_at > now
    free_trial = FreeTrialDetail(
        active=trial_active,
        expires_at=trial.expires_at if trial else None,
    )

    return CommonResponse.ok(MySubscriptionResponse(subscription=subscription_detail, free_trial=free_trial))
