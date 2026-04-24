import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Plan, Subscription
from app.models.user import FreeTrial, User


async def user_has_access(
    db: AsyncSession,
    user: User,
    subject_id: uuid.UUID,
    class_number: int,
) -> bool:
    if user.role == "admin":
        return True

    now = datetime.now(timezone.utc)

    trial_result = await db.execute(
        select(FreeTrial).where(
            FreeTrial.user_id == user.id,
            FreeTrial.expires_at > now,
        )
    )
    if trial_result.scalar_one_or_none():
        return True

    subs_result = await db.execute(
        select(Subscription, Plan)
        .join(Plan, Subscription.plan_id == Plan.id)
        .where(
            Subscription.user_id == user.id,
            Subscription.status == "active",
            or_(
                Subscription.expires_at.is_(None),
                Subscription.expires_at > now,
            ),
        )
    )
    for sub, plan in subs_result.all():
        if plan.plan_type == "full_access":
            return True
        if plan.plan_type in ("complete", "seasonal"):
            if plan.class_numbers and class_number in plan.class_numbers:
                return True
        if plan.plan_type in ("bundle", "single_subject", "lifetime"):
            if plan.subject_ids and subject_id in plan.subject_ids:
                return True

    return False
