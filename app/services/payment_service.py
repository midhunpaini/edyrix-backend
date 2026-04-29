import hashlib
import hmac
import uuid

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.subscription import Payment, Plan

_RAZORPAY_API = "https://api.razorpay.com/v1"


async def create_razorpay_order(
    db: AsyncSession, plan_id: uuid.UUID, user_id: uuid.UUID
) -> Payment:
    result = await db.execute(select(Plan).where(Plan.id == plan_id, Plan.is_active.is_(True)))
    plan = result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_RAZORPAY_API}/orders",
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
            json={
                "amount": plan.price_paise,
                "currency": "INR",
                "receipt": str(uuid.uuid4())[:30],
            },
            timeout=10.0,
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Failed to create Razorpay order")

    rz_order = resp.json()

    payment = Payment(
        user_id=user_id,
        plan_id=plan_id,
        razorpay_order_id=rz_order["id"],
        amount_paise=plan.price_paise,
        status="pending",
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)
    return payment


def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
    message = f"{order_id}|{payment_id}"
    expected = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def issue_refund(razorpay_payment_id: str, amount_paise: int) -> dict:
    """Issue a Razorpay refund and return the refund object. Raises HTTPException on failure."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_RAZORPAY_API}/payments/{razorpay_payment_id}/refund",
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
            json={"amount": amount_paise},
            timeout=15.0,
        )
    if resp.status_code not in (200, 201):
        raise HTTPException(status_code=400, detail=f"Razorpay refund failed: {resp.text}")
    return resp.json()


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    expected = hmac.new(
        settings.RAZORPAY_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
