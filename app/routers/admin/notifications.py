from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_admin
from app.models.admin import AdminUser
from app.models.notification import NotificationLog
from app.schemas.admin import (
    NotificationLogItem,
    SendNotificationRequest,
    SendNotificationResponse,
)
from app.schemas.common import CommonResponse
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["admin:notifications"])


@router.post("/send", response_model=CommonResponse[SendNotificationResponse])
async def send_notification(
    body: SendNotificationRequest,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[SendNotificationResponse]:
    now = datetime.now(timezone.utc)
    user_ids, tokens = await notification_service.resolve_segment_tokens(db, body.target_segment)
    target_count = len(user_ids)
    sent_count, failed_count = await notification_service.send_multicast(tokens, body.title, body.body, body.data)

    log = NotificationLog(
        title=body.title,
        body=body.body,
        target_segment=body.target_segment,
        target_count=target_count,
        sent_count=sent_count,
        failed_count=failed_count,
        data=body.data,
        created_by=None,
        scheduled_at=body.scheduled_at,
        sent_at=now,
        status="sent" if sent_count > 0 else "failed",
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)

    return CommonResponse.ok(SendNotificationResponse(
        log_id=log.id,
        target_count=target_count,
        sent_count=sent_count,
        failed_count=failed_count,
    ))


@router.get("/history", response_model=CommonResponse[list[NotificationLogItem]])
async def notification_history(
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[list[NotificationLogItem]]:
    results = await db.execute(
        select(NotificationLog).order_by(NotificationLog.created_at.desc()).limit(50)
    )
    return CommonResponse.ok([NotificationLogItem.model_validate(n) for n in results.scalars().all()])
