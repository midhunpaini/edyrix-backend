from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.exceptions import BadRequestException, NotFoundException
from app.models.subscription import Plan
from app.models.user import User
from app.schemas.common import CommonResponse
from app.schemas.content import (
    ChapterDetailResponse,
    ClassSummary,
    LessonPlayResponse,
    NotesResponse,
    SubjectDetailResponse,
    SubjectListItem,
)
from app.schemas.subscription import PlanResponse
from app.services import content_service as svc
from app.services.auth_service import decode_access_token, is_token_valid

router = APIRouter(tags=["content"])
_optional_bearer = HTTPBearer(auto_error=False)


async def _optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if credentials is None:
        return None
    try:
        payload = decode_access_token(credentials.credentials)
        jti: str | None = payload.get("jti")
        user_id: str | None = payload.get("sub")
        token_type: str | None = payload.get("typ")
        if not jti or not user_id or token_type != "student" or not await is_token_valid(jti, db):
            return None
        result = await db.execute(
            select(User).where(User.id == user_id, User.role == "student", User.is_active.is_(True))
        )
        return result.scalar_one_or_none()
    except Exception:
        return None


@router.get("/classes", response_model=CommonResponse[list[ClassSummary]])
async def list_classes(db: AsyncSession = Depends(get_db)) -> CommonResponse[list[ClassSummary]]:
    return CommonResponse.ok(await svc.get_classes(db))


@router.get("/classes/{class_number}/subjects", response_model=CommonResponse[list[SubjectListItem]])
async def list_subjects(
    class_number: int,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(_optional_user),
) -> CommonResponse[list[SubjectListItem]]:
    if class_number not in range(7, 11):
        raise BadRequestException("class_number must be 7–10")
    return CommonResponse.ok(await svc.get_subjects_by_class(db, class_number, user))


@router.get("/subjects/{subject_id}", response_model=CommonResponse[SubjectDetailResponse])
async def get_subject(
    subject_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[SubjectDetailResponse]:
    result = await svc.get_subject_detail(db, subject_id, user)
    if result is None:
        raise NotFoundException("Subject not found")
    return CommonResponse.ok(result)


@router.get("/chapters/{chapter_id}", response_model=CommonResponse[ChapterDetailResponse])
async def get_chapter(
    chapter_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[ChapterDetailResponse]:
    result = await svc.get_chapter_detail(db, chapter_id, user)
    if result is None:
        raise NotFoundException("Chapter not found")
    return CommonResponse.ok(result)


@router.get("/chapters/{chapter_id}/notes", response_model=CommonResponse[NotesResponse])
async def get_notes(
    chapter_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[NotesResponse]:
    try:
        result = await svc.get_chapter_notes(db, chapter_id, user)
    except svc.AccessDenied as exc:
        slugs = await svc.get_relevant_plan_slugs(db, exc.subject_id, exc.class_number)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"detail": "subscription_required", "plan_options": slugs},
        )
    if result is None:
        raise NotFoundException("Notes not found")
    return CommonResponse.ok(result)


@router.get("/lessons/{lesson_id}/play", response_model=CommonResponse[LessonPlayResponse])
async def play_lesson(
    lesson_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[LessonPlayResponse]:
    try:
        result = await svc.get_lesson_play(db, lesson_id, user)
    except svc.AccessDenied as exc:
        slugs = await svc.get_relevant_plan_slugs(db, exc.subject_id, exc.class_number)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"detail": "subscription_required", "plan_options": slugs},
        )
    if result is None:
        raise NotFoundException("Lesson not found")
    return CommonResponse.ok(result)


@router.get("/plans", response_model=CommonResponse[list[PlanResponse]])
async def list_plans(db: AsyncSession = Depends(get_db)) -> CommonResponse[list[PlanResponse]]:
    result = await db.execute(
        select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.order_index)
    )
    return CommonResponse.ok(list(result.scalars()))
