import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_admin
from app.exceptions import BadRequestException, NotFoundException
from app.models.admin import AdminUser
from app.models.subscription import Payment, Plan, Subscription
from app.models.user import User
from app.schemas.admin import (
    RefundResponse,
    RevenueForecastResponse,
    RevenueResponse,
    SubscriptionListItem,
    SubscriptionListResponse,
)
from app.schemas.common import CommonResponse
from app.services import analytics_service
from app.services.payment_service import issue_refund
from app.utils.audit import log_audit

router = APIRouter(tags=["admin:revenue"])


@router.get("/revenue", response_model=CommonResponse[RevenueResponse])
async def get_revenue(
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    plan_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[RevenueResponse]:
    now = datetime.now(timezone.utc)
    start = datetime.fromisoformat(start_date) if start_date else now - timedelta(days=30)
    end = datetime.fromisoformat(end_date) if end_date else now

    result = await analytics_service.get_revenue_data(db, start, end, plan_id)
    return CommonResponse.ok(RevenueResponse(**result))


@router.get("/revenue/forecast", response_model=CommonResponse[RevenueForecastResponse])
async def get_revenue_forecast(
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[RevenueForecastResponse]:
    result = await analytics_service.get_revenue_forecast(db)
    return CommonResponse.ok(RevenueForecastResponse(**result))


@router.get("/subscriptions", response_model=CommonResponse[SubscriptionListResponse])
async def list_subscriptions(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sub_status: str | None = Query(None, alias="status"),
    plan_id: uuid.UUID | None = Query(None),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[SubscriptionListResponse]:
    offset = (page - 1) * limit

    base_q = (
        select(Subscription, User, Plan)
        .join(User, Subscription.user_id == User.id)
        .join(Plan, Subscription.plan_id == Plan.id)
    )
    count_q = select(func.count()).select_from(
        select(Subscription).join(User, Subscription.user_id == User.id).join(Plan, Subscription.plan_id == Plan.id).subquery()
    )

    if sub_status:
        base_q = base_q.where(Subscription.status == sub_status)
    if plan_id:
        base_q = base_q.where(Subscription.plan_id == plan_id)
    if search:
        like = f"%{search}%"
        base_q = base_q.where(or_(User.name.ilike(like), User.phone.ilike(like)))

    total = (await db.execute(count_q)).scalar() or 0
    rows = (await db.execute(base_q.order_by(Subscription.created_at.desc()).limit(limit).offset(offset))).all()

    payment_map: dict[uuid.UUID, uuid.UUID | None] = {}
    if rows:
        sub_ids = [r[0].id for r in rows]
        pay_rows = await db.execute(
            select(Payment.subscription_id, Payment.id)
            .where(Payment.subscription_id.in_(sub_ids), Payment.status == "success")
            .order_by(Payment.created_at.desc())
        )
        for pr in pay_rows.all():
            if pr[0] not in payment_map:
                payment_map[pr[0]] = pr[1]

    items = [
        SubscriptionListItem(
            id=r[0].id,
            student_name=r[1].name,
            student_phone=r[1].phone,
            plan_name=r[2].name,
            amount_paise=r[2].price_paise,
            started_at=r[0].started_at,
            expires_at=r[0].expires_at,
            status=r[0].status,
            payment_id=payment_map.get(r[0].id),
        )
        for r in rows
    ]
    return CommonResponse.ok(SubscriptionListResponse(total=total, subscriptions=items))


@router.post("/payments/{payment_id}/refund", response_model=CommonResponse[RefundResponse])
async def refund_payment(
    payment_id: uuid.UUID,
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
) -> CommonResponse[RefundResponse]:
    payment = (await db.execute(select(Payment).where(Payment.id == payment_id))).scalar_one_or_none()
    if payment is None:
        raise NotFoundException("Payment not found")
    if payment.status == "refunded":
        raise BadRequestException("Already refunded")
    if not payment.razorpay_payment_id:
        raise BadRequestException("No Razorpay payment ID on record")

    rz = await issue_refund(payment.razorpay_payment_id, payment.amount_paise)
    payment.status = "refunded"

    if payment.subscription_id:
        sub = (await db.execute(select(Subscription).where(Subscription.id == payment.subscription_id))).scalar_one_or_none()
        if sub:
            sub.status = "cancelled"
            sub.cancelled_at = datetime.now(timezone.utc)

    await log_audit(db, admin.id, "payment.refund", "payment", payment_id, {"razorpay_refund_id": rz.get("id"), "reason": body.get("reason", "")}, request)
    await db.commit()

    return CommonResponse.ok(RefundResponse(refund_id=rz.get("id", ""), status="success"))
