from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, require_admin
from app.models.doubt import Doubt
from app.models.user import User
from app.schemas.doubt import (
    AnswerDoubtRequest,
    AnswerDoubtResponse,
    DoubtCreateRequest,
    DoubtCreateResponse,
    DoubtListItem,
)
from app.services import notification_service
from app.services.email_service import send_doubt_answered_email

router = APIRouter(prefix="/doubts", tags=["doubts"])


@router.post("", response_model=DoubtCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_doubt(
    body: DoubtCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DoubtCreateResponse:
    doubt = Doubt(
        user_id=user.id,
        lesson_id=body.lesson_id,
        chapter_id=body.chapter_id,
        question_text=body.question_text,
        status="pending",
    )
    db.add(doubt)
    await db.commit()
    await db.refresh(doubt)
    return DoubtCreateResponse(id=doubt.id, status=doubt.status)


@router.get("", response_model=list[DoubtListItem])
async def list_doubts(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DoubtListItem]:
    result = await db.execute(
        select(Doubt)
        .where(Doubt.user_id == user.id)
        .order_by(Doubt.created_at.desc())
    )
    doubts = result.scalars().all()
    return [
        DoubtListItem(
            id=d.id,
            question_text=d.question_text,
            status=d.status,
            answer_text=d.answer_text,
            created_at=d.created_at,
            answered_at=d.answered_at,
        )
        for d in doubts
    ]


@router.put("/{doubt_id}/answer", response_model=AnswerDoubtResponse)
async def answer_doubt(
    doubt_id: str,
    body: AnswerDoubtRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> AnswerDoubtResponse:
    result = await db.execute(select(Doubt).where(Doubt.id == doubt_id))
    doubt = result.scalar_one_or_none()
    if doubt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Doubt not found")

    doubt.answer_text = body.answer_text
    doubt.answered_by = admin.id
    doubt.answered_at = datetime.now(timezone.utc)
    doubt.status = "answered"
    await db.commit()
    await db.refresh(doubt)

    student_result = await db.execute(
        select(User).where(User.id == doubt.user_id)  # type: ignore[arg-type]
    )
    student = student_result.scalar_one_or_none()

    notif_sent = await notification_service.send_doubt_answered(
        db, doubt.user_id, doubt.question_text  # type: ignore[arg-type]
    )

    if student and student.email:
        send_doubt_answered_email(student.email, doubt.question_text, body.answer_text)

    return AnswerDoubtResponse(message="Doubt answered", notification_sent=notif_sent)
