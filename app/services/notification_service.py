import asyncio
import functools
import uuid

from firebase_admin import messaging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import FCMToken
from app.services.auth_service import _ensure_firebase


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
