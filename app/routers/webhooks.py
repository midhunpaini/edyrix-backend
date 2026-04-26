import json

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.services import payment_service, subscription_service

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    if not payment_service.verify_webhook_signature(body, signature):
        return Response(status_code=200)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return Response(status_code=200)

    event = payload.get("event")

    if event == "payment.captured":
        entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        payment_id = entity.get("id", "")
        order_id = entity.get("order_id", "")
        if order_id and payment_id:
            await subscription_service.activate_from_webhook(db, order_id, payment_id)

    elif event == "subscription.cancelled":
        entity = payload.get("payload", {}).get("subscription", {}).get("entity", {})
        razorpay_sub_id = entity.get("id", "")
        if razorpay_sub_id:
            await subscription_service.cancel_by_razorpay_id(db, razorpay_sub_id)

    return Response(status_code=200)
