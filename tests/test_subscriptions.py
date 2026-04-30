"""
Unit tests for subscription_service business logic.

All DB calls are mocked with AsyncMock — no PostgreSQL required.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from fastapi import HTTPException

from app.models.subscription import Payment, Plan, Subscription
from app.services.subscription_service import (
    _calc_expiry,
    activate_from_webhook,
    activate_subscription,
    cancel_by_razorpay_id,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _result(value):
    """Return a mock that looks like an AsyncSession execute() result."""
    m = MagicMock()
    m.scalar_one_or_none.return_value = value
    return m


def _make_plan(billing_cycle: str = "monthly") -> Plan:
    plan = Plan(
        name="Test Plan",
        slug=f"test-{billing_cycle}",
        plan_type="full_access",
        billing_cycle=billing_cycle,
        price_paise=14900,
        features=[],
    )
    plan.id = uuid.uuid4()
    return plan


def _make_payment(user_id: uuid.UUID, plan_id: uuid.UUID, status: str = "pending") -> Payment:
    payment = Payment(
        user_id=user_id,
        razorpay_order_id="order_test_123",
        amount_paise=14900,
        status=status,
        plan_id=plan_id,
    )
    payment.id = uuid.uuid4()
    payment.subscription_id = None
    payment.razorpay_payment_id = None
    payment.razorpay_signature = None
    return payment


# ── _calc_expiry (pure) ───────────────────────────────────────────────────────

def test_calc_expiry_monthly_is_roughly_30_days():
    before = datetime.now(timezone.utc)
    result = _calc_expiry("monthly")
    delta = result - before
    assert 29 <= delta.days <= 30


def test_calc_expiry_annual_is_roughly_365_days():
    before = datetime.now(timezone.utc)
    result = _calc_expiry("annual")
    delta = result - before
    assert 364 <= delta.days <= 365


def test_calc_expiry_lifetime_returns_none():
    assert _calc_expiry("lifetime") is None


def test_calc_expiry_one_time_returns_none():
    assert _calc_expiry("one_time") is None


# ── activate_subscription ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_activate_subscription_creates_subscription(mock_db, test_user):
    plan = _make_plan("monthly")
    payment = _make_payment(test_user.id, plan.id)

    mock_db.execute.side_effect = [_result(payment), _result(plan)]

    sub, returned_plan = await activate_subscription(
        mock_db, payment.razorpay_order_id, "pay_abc", "sig_xyz", test_user.id
    )

    assert sub.status == "active"
    assert sub.user_id == test_user.id
    assert sub.razorpay_payment_id == "pay_abc"
    assert sub.expires_at is not None  # monthly → has expiry
    assert returned_plan is plan
    mock_db.add.assert_called_once()
    mock_db.flush.assert_awaited_once()
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_activate_subscription_lifetime_has_no_expiry(mock_db, test_user):
    plan = _make_plan("lifetime")
    payment = _make_payment(test_user.id, plan.id)

    mock_db.execute.side_effect = [_result(payment), _result(plan)]

    sub, _ = await activate_subscription(
        mock_db, payment.razorpay_order_id, "pay_life", "sig_life", test_user.id
    )

    assert sub.expires_at is None


@pytest.mark.asyncio
async def test_activate_subscription_payment_not_found_raises_400(mock_db, test_user):
    mock_db.execute.return_value = _result(None)

    with pytest.raises(HTTPException) as exc_info:
        await activate_subscription(mock_db, "order_ghost", "pay_x", "sig_x", test_user.id)

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_activate_subscription_wrong_user_raises_403(mock_db, test_user):
    other_user_id = uuid.uuid4()
    plan = _make_plan()
    payment = _make_payment(other_user_id, plan.id)  # belongs to a different user

    mock_db.execute.side_effect = [_result(payment), _result(plan)]

    with pytest.raises(HTTPException) as exc_info:
        await activate_subscription(
            mock_db, payment.razorpay_order_id, "pay_x", "sig_x", test_user.id
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_activate_subscription_plan_not_found_raises_400(mock_db, test_user):
    plan = _make_plan()
    payment = _make_payment(test_user.id, plan.id)

    mock_db.execute.side_effect = [_result(payment), _result(None)]  # plan missing

    with pytest.raises(HTTPException) as exc_info:
        await activate_subscription(
            mock_db, payment.razorpay_order_id, "pay_x", "sig_x", test_user.id
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_activate_subscription_idempotent_returns_existing(mock_db, test_user):
    """Double-verify call returns the already-created subscription without a new DB row."""
    plan = _make_plan()
    payment = _make_payment(test_user.id, plan.id, status="success")
    existing_sub_id = uuid.uuid4()
    payment.subscription_id = existing_sub_id

    existing_sub = MagicMock(spec=Subscription)
    existing_sub.id = existing_sub_id
    existing_sub.status = "active"

    mock_db.execute.side_effect = [_result(payment), _result(plan)]
    mock_db.get.return_value = existing_sub

    sub, _ = await activate_subscription(
        mock_db, payment.razorpay_order_id, "pay_dup", "sig_dup", test_user.id
    )

    assert sub is existing_sub
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_awaited()


# ── activate_from_webhook ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_activate_from_webhook_creates_subscription(mock_db):
    user_id = uuid.uuid4()
    plan = _make_plan("annual")
    payment = _make_payment(user_id, plan.id, status="pending")

    mock_db.execute.side_effect = [_result(payment), _result(plan)]

    await activate_from_webhook(mock_db, payment.razorpay_order_id, "pay_wh_123")

    assert payment.status == "success"
    assert payment.razorpay_payment_id == "pay_wh_123"
    mock_db.add.assert_called_once()
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_activate_from_webhook_no_op_when_already_activated(mock_db):
    """Webhook for an already-activated order is silently ignored."""
    mock_db.execute.return_value = _result(None)  # query with status != "success" finds nothing

    await activate_from_webhook(mock_db, "order_done", "pay_done")

    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_activate_from_webhook_no_op_when_plan_missing(mock_db):
    user_id = uuid.uuid4()
    plan = _make_plan()
    payment = _make_payment(user_id, plan.id)

    mock_db.execute.side_effect = [_result(payment), _result(None)]  # plan gone

    await activate_from_webhook(mock_db, payment.razorpay_order_id, "pay_x")

    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_awaited()


# ── cancel_by_razorpay_id ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_sets_status_and_timestamp(mock_db):
    sub = MagicMock(spec=Subscription)
    sub.status = "active"
    sub.cancelled_at = None

    mock_db.execute.return_value = _result(sub)

    await cancel_by_razorpay_id(mock_db, "sub_rzp_live_123")

    assert sub.status == "cancelled"
    assert sub.cancelled_at is not None
    cancelled_delta = datetime.now(timezone.utc) - sub.cancelled_at
    assert cancelled_delta.total_seconds() < 5  # stamped within the last 5 seconds
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_no_op_when_subscription_not_found(mock_db):
    """Unknown or already-cancelled subscription ID should not raise."""
    mock_db.execute.return_value = _result(None)

    await cancel_by_razorpay_id(mock_db, "sub_not_found")

    mock_db.commit.assert_not_awaited()
