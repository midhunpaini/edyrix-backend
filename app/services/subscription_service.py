import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Payment, Plan, Subscription


def _calc_expiry(billing_cycle: str) -> datetime | None:
    now = datetime.now(timezone.utc)
    if billing_cycle == "monthly":
        return now + timedelta(days=30)
    if billing_cycle == "annual":
        return now + timedelta(days=365)
    return None  # one_time / lifetime


async def activate_subscription(
    db: AsyncSession,
    order_id: str,
    payment_id: str,
    signature: str,
    user_id: uuid.UUID,
) -> tuple["Subscription", "Plan"]:
    # WITH FOR UPDATE serialises concurrent verify calls on the same order, preventing
    # duplicate subscriptions if the user clicks "verify" twice simultaneously.
    result = await db.execute(select(Payment).where(Payment.razorpay_order_id == order_id).with_for_update())
    payment = result.scalar_one_or_none()
    if payment is None:
        raise HTTPException(status_code=400, detail="Payment record not found")

    if payment.user_id != user_id:
        raise HTTPException(status_code=403, detail="Payment does not belong to this user")

    plan_result = await db.execute(select(Plan).where(Plan.id == payment.plan_id))
    plan = plan_result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=400, detail="Plan not found")

    if payment.status == "success" and payment.subscription_id is not None:
        sub = await db.get(Subscription, payment.subscription_id)
        if sub:
            return sub, plan

    payment.status = "success"
    payment.razorpay_payment_id = payment_id
    payment.razorpay_signature = signature

    sub = Subscription(
        user_id=user_id,
        plan_id=plan.id,
        razorpay_payment_id=payment_id,
        status="active",
        expires_at=_calc_expiry(plan.billing_cycle),
    )
    db.add(sub)
    await db.flush()
    payment.subscription_id = sub.id
    await db.commit()
    await db.refresh(sub)
    return sub, plan


async def activate_from_webhook(
    db: AsyncSession, order_id: str, payment_id: str
) -> None:
    # WITH FOR UPDATE prevents duplicate subscriptions if the webhook fires while the
    # user's verify request is also in-flight for the same order.
    result = await db.execute(
        select(Payment).where(
            Payment.razorpay_order_id == order_id,
            Payment.status != "success",
        ).with_for_update()
    )
    payment = result.scalar_one_or_none()
    if payment is None:
        return

    plan_result = await db.execute(select(Plan).where(Plan.id == payment.plan_id))
    plan = plan_result.scalar_one_or_none()
    if plan is None:
        return

    payment.status = "success"
    payment.razorpay_payment_id = payment_id

    sub = Subscription(
        user_id=payment.user_id,
        plan_id=plan.id,
        razorpay_payment_id=payment_id,
        status="active",
        expires_at=_calc_expiry(plan.billing_cycle),
    )
    db.add(sub)
    await db.flush()
    payment.subscription_id = sub.id
    await db.commit()


async def cancel_by_razorpay_id(db: AsyncSession, razorpay_subscription_id: str) -> None:
    result = await db.execute(
        select(Subscription).where(
            Subscription.razorpay_subscription_id == razorpay_subscription_id,
            Subscription.status == "active",
        )
    )
    sub = result.scalar_one_or_none()
    if sub:
        sub.status = "cancelled"
        sub.cancelled_at = datetime.now(timezone.utc)
        await db.commit()
