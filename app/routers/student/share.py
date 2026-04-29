from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import ShareEvent, User
from app.schemas.common import CommonResponse, MessageResponse
from app.schemas.user import ShareRequest

router = APIRouter(prefix="/share", tags=["student:share"])


@router.post("", response_model=CommonResponse[MessageResponse])
async def record_share(
    body: ShareRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[MessageResponse]:
    db.add(ShareEvent(
        user_id=user.id,
        event_type=body.event_type,
        reference_id=body.reference_id,
        platform=body.platform,
    ))
    await db.commit()
    return CommonResponse.ok(MessageResponse(message="Recorded"))
