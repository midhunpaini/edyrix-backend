from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.doubt import Doubt
from app.models.user import User
from app.schemas.doubt import (
    DoubtCreateRequest,
    DoubtCreateResponse,
    DoubtListItem,
)

router = APIRouter(prefix="/doubts", tags=["doubts"])


@router.post("", response_model=DoubtCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_doubt(
    body: DoubtCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DoubtCreateResponse:
    """Submit a new doubt question."""
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
    """Return all doubts submitted by the current user."""
    result = await db.execute(
        select(Doubt)
        .where(Doubt.user_id == user.id)
        .order_by(Doubt.created_at.desc())
    )
    return [
        DoubtListItem(
            id=d.id,
            question_text=d.question_text,
            status=d.status,
            answer_text=d.answer_text,
            created_at=d.created_at,
            answered_at=d.answered_at,
        )
        for d in result.scalars().all()
    ]
