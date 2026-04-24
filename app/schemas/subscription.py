from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    plan_type: str
    billing_cycle: str
    price_paise: int
    original_price_paise: int | None
    is_featured: bool
    features: list[str]
    description: str | None = None


class CreateOrderRequest(BaseModel):
    plan_id: UUID


class CreateOrderResponse(BaseModel):
    order_id: str
    amount: int
    currency: str
    razorpay_key_id: str


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class SubscriptionSummary(BaseModel):
    id: UUID
    plan_name: str
    status: str
    expires_at: datetime | None


class VerifyPaymentResponse(BaseModel):
    message: str
    subscription: SubscriptionSummary


class SubscriptionDetail(BaseModel):
    id: UUID
    plan: PlanResponse
    status: str
    started_at: datetime
    expires_at: datetime | None
    auto_renew: bool


class FreeTrialDetail(BaseModel):
    active: bool
    expires_at: datetime | None


class MySubscriptionResponse(BaseModel):
    subscription: SubscriptionDetail | None
    free_trial: FreeTrialDetail


class CancelSubscriptionResponse(BaseModel):
    message: str
