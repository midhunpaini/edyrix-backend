from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.exceptions import BadRequestException
from app.limiter import limiter
from app.models.user import User
from app.schemas.common import CommonResponse
from app.schemas.subscription import (
    CreateOrderRequest,
    CreateOrderResponse,
    SubscriptionSummary,
    VerifyPaymentRequest,
    VerifyPaymentResponse,
)
from app.services import payment_service, subscription_service

router = APIRouter(prefix="/payments", tags=["student:payments"])


@router.post("/create-order", response_model=CommonResponse[CreateOrderResponse], status_code=201)
@limiter.limit("20/minute")
async def create_order(
    request: Request,
    body: CreateOrderRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[CreateOrderResponse]:
    payment = await payment_service.create_razorpay_order(db, body.plan_id, user.id)
    return CommonResponse.ok(CreateOrderResponse(
        order_id=payment.razorpay_order_id,
        amount=payment.amount_paise,
        currency=payment.currency,
        razorpay_key_id=settings.RAZORPAY_KEY_ID,
    ))


@router.post("/verify", response_model=CommonResponse[VerifyPaymentResponse])
async def verify_payment(
    body: VerifyPaymentRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[VerifyPaymentResponse]:
    if not payment_service.verify_payment_signature(
        body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature
    ):
        raise BadRequestException("Payment verification failed")

    sub, plan = await subscription_service.activate_subscription(
        db,
        body.razorpay_order_id,
        body.razorpay_payment_id,
        body.razorpay_signature,
        user.id,
    )
    return CommonResponse.ok(VerifyPaymentResponse(
        message="Subscription activated",
        subscription=SubscriptionSummary(
            id=sub.id,
            plan_name=plan.name,
            status=sub.status,
            expires_at=sub.expires_at,
        ),
    ))
