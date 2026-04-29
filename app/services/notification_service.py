import asyncio
import functools
import uuid
from datetime import datetime, timedelta, timezone

from firebase_admin import messaging
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import BadRequestException
from app.models.progress import TestAttempt, WatchHistory
from app.models.subscription import Subscription
from app.models.user import FCMToken, FreeTrial, User
from app.services.auth_service import _ensure_firebase

_VALID_SEGMENTS = {"all", "trial", "subscribed", "inactive_7d", "class_10", "class_9", "class_8", "class_7"}


async def send_doubt_answered(
    db: AsyncSession,
    user_id: uuid.UUID,
    question_preview: str,
) -> bool:
    """Send an FCM push notification to all of a user's registered devices."""
    _ensure_firebase()

    result = await db.execute(select(FCMToken).where(FCMToken.user_id == user_id))
    tokens = result.scalars().all()
    if not tokens:
        return False

    loop = asyncio.get_running_loop()
    sent = False
    for fcm_token in tokens:
        message = messaging.Message(
            notification=messaging.Notification(
                title="Your doubt has been answered!",
                body=question_preview[:80],
            ),
            token=fcm_token.token,
        )
        try:
            await loop.run_in_executor(None, functools.partial(messaging.send, message))
            sent = True
        except Exception:
            pass

    return sent


async def resolve_segment_tokens(
    db: AsyncSession, segment: str
) -> tuple[list[uuid.UUID], list[str]]:
    if segment not in _VALID_SEGMENTS:
        raise BadRequestException(f"Invalid target_segment. Must be one of: {', '.join(_VALID_SEGMENTS)}")

    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)

    if segment == "all":
        users_q = select(User.id).where(User.is_active.is_(True), User.is_suspended.is_(False))
    elif segment == "trial":
        users_q = select(FreeTrial.user_id).join(User, User.id == FreeTrial.user_id).where(
            FreeTrial.expires_at > now, User.is_active.is_(True)
        )
    elif segment == "subscribed":
        users_q = select(Subscription.user_id).join(User, User.id == Subscription.user_id).where(
            Subscription.status == "active",
            or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
            User.is_active.is_(True),
        )
    elif segment == "inactive_7d":
        active_users_sq = (
            select(WatchHistory.user_id)
            .where(WatchHistory.last_watched_at >= seven_days_ago)
            .union(select(TestAttempt.user_id).where(TestAttempt.completed_at >= seven_days_ago))
        ).subquery()
        users_q = select(User.id).where(
            User.role == "student",
            User.is_active.is_(True),
            ~User.id.in_(select(active_users_sq.c.user_id)),
        )
    else:
        class_num = int(segment.split("_")[1])
        users_q = select(User.id).where(
            User.current_class == class_num, User.is_active.is_(True), User.is_suspended.is_(False)
        )

    user_ids = [r[0] for r in (await db.execute(users_q)).all()]
    tokens = [
        r[0] for r in (
            await db.execute(select(FCMToken.token).where(FCMToken.user_id.in_(user_ids)))
        ).all()
    ]
    return user_ids, tokens


async def send_multicast(
    tokens: list[str],
    title: str,
    body: str,
    data: dict | None = None,
) -> tuple[int, int]:
    if not tokens:
        return 0, 0

    _ensure_firebase()
    loop = asyncio.get_running_loop()
    sent_count = 0
    failed_count = 0
    for i in range(0, len(tokens), 500):
        batch = tokens[i:i + 500]
        mm = messaging.MulticastMessage(
            notification=messaging.Notification(title=title, body=body),
            data=data,
            tokens=batch,
        )
        try:
            response = await loop.run_in_executor(
                None, functools.partial(messaging.send_each_for_multicast, mm)
            )
            sent_count += response.success_count
            failed_count += response.failure_count
        except Exception:
            failed_count += len(batch)

    return sent_count, failed_count
