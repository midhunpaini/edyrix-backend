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
    _ensure_firebase()

    result = await db.execute(
        select(FCMToken).where(FCMToken.user_id == user_id)
    )
    tokens = result.scalars().all()
    if not tokens:
        return False

    sent = False
    for fcm_token in tokens:
        try:
            messaging.send(
                messaging.Message(
                    notification=messaging.Notification(
                        title="Your doubt has been answered!",
                        body=question_preview[:80],
                    ),
                    token=fcm_token.token,
                )
            )
            sent = True
        except Exception:
            pass

    return sent
