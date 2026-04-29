import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.dependencies import get_db, require_admin
from app.exceptions import NotFoundException
from app.models.admin import AdminUser
from app.models.content import Chapter, Subject
from app.models.doubt import Doubt
from app.models.doubt_template import DoubtTemplate
from app.models.user import User
from app.queue import enqueue
from app.schemas.admin import (
    AdminDoubtItem,
    AdminDoubtListResponse,
    AssignDoubtRequest,
    BulkCloseRequest,
    CloseDoubtRequest,
    DoubtStatsResponse,
    DoubtTemplateCreate,
    DoubtTemplateResponse,
)
from app.schemas.common import CommonResponse
from app.schemas.doubt import AnswerDoubtRequest, AnswerDoubtResponse
from app.utils.audit import log_audit

router = APIRouter(tags=["admin:doubts"])


@router.get("/doubts/stats", response_model=CommonResponse[DoubtStatsResponse])
async def get_doubt_stats(
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[DoubtStatsResponse]:
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    pending_count = (
        await db.execute(select(func.count(Doubt.id)).where(Doubt.status == "pending"))
    ).scalar() or 0

    answered_today = (
        await db.execute(
            select(func.count(Doubt.id)).where(Doubt.status == "answered", Doubt.answered_at >= today_start)
        )
    ).scalar() or 0

    sla_breached = (
        await db.execute(select(func.count(Doubt.id)).where(Doubt.sla_breached.is_(True), Doubt.status == "pending"))
    ).scalar() or 0

    avg_hours_row = await db.execute(
        select(func.coalesce(func.avg(
            func.extract("epoch", Doubt.answered_at - Doubt.created_at) / 3600
        ), 0)).where(Doubt.status == "answered", Doubt.answered_at.isnot(None))
    )
    avg_response_hours = round(float(avg_hours_row.scalar() or 0), 1)

    oldest_row = await db.execute(
        select(func.min(Doubt.created_at)).where(Doubt.status == "pending")
    )
    oldest_created = oldest_row.scalar()
    oldest_hours = (
        round((now - oldest_created).total_seconds() / 3600, 1) if oldest_created else 0.0
    )

    by_subject_result = await db.execute(
        select(Subject.name, func.count(Doubt.id))
        .join(Chapter, Doubt.chapter_id == Chapter.id, isouter=True)
        .join(Subject, Chapter.subject_id == Subject.id, isouter=True)
        .where(Doubt.status == "pending")
        .group_by(Subject.name)
    )
    by_subject = [{"subject": r[0] or "Unknown", "pending": r[1]} for r in by_subject_result.all()]

    return CommonResponse.ok(DoubtStatsResponse(
        pending_count=pending_count,
        avg_response_hours=avg_response_hours,
        answered_today=answered_today,
        oldest_pending_hours=oldest_hours,
        sla_breached_count=sla_breached,
        by_subject=by_subject,
    ))


@router.get("/doubts", response_model=CommonResponse[AdminDoubtListResponse])
async def list_doubts(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Literal["pending", "answered", "closed"] | None = Query(None, alias="status"),
    assigned_to: uuid.UUID | None = Query(None),
    subject_id: uuid.UUID | None = Query(None),
    chapter_id: uuid.UUID | None = Query(None),
    sort: Literal["oldest", "newest"] = Query("oldest"),
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[AdminDoubtListResponse]:
    now = datetime.now(timezone.utc)
    offset = (page - 1) * limit

    StudentUser = aliased(User)
    AssignedUser = aliased(User)

    count_q = select(func.count(Doubt.id))
    fetch_q = (
        select(Doubt, StudentUser, AssignedUser, Chapter, Subject)
        .outerjoin(StudentUser, Doubt.user_id == StudentUser.id)
        .outerjoin(AssignedUser, Doubt.assigned_to == AssignedUser.id)
        .outerjoin(Chapter, Doubt.chapter_id == Chapter.id)
        .outerjoin(Subject, Chapter.subject_id == Subject.id)
    )

    filters = []
    if status_filter:
        filters.append(Doubt.status == status_filter)
    if assigned_to:
        filters.append(Doubt.assigned_to == assigned_to)
    if chapter_id:
        filters.append(Doubt.chapter_id == chapter_id)
    if subject_id:
        filters.append(Chapter.subject_id == subject_id)

    for f in filters:
        count_q = count_q.where(f)
        fetch_q = fetch_q.where(f)

    order = Doubt.created_at.asc() if sort == "oldest" else Doubt.created_at.desc()
    fetch_q = fetch_q.order_by(order).limit(limit).offset(offset)

    total = (await db.execute(count_q)).scalar() or 0
    rows = (await db.execute(fetch_q)).all()

    items = []
    for d, student, assigned, chapter, subject in rows:
        hours_pending = None
        if d.status == "pending":
            hours_pending = round((now - d.created_at).total_seconds() / 3600, 1)
        items.append(AdminDoubtItem(
            id=d.id,
            student_name=student.name if student else "Unknown",
            student_class=student.current_class if student else None,
            subject_name=subject.name if subject else None,
            chapter_title=chapter.title if chapter else None,
            question_text=d.question_text,
            chapter_id=d.chapter_id,
            lesson_id=d.lesson_id,
            status=d.status,
            assigned_to_id=d.assigned_to,
            assigned_to_name=assigned.name if assigned else None,
            hours_pending=hours_pending,
            sla_breached=d.sla_breached,
            image_url=None,
            created_at=d.created_at,
        ))

    return CommonResponse.ok(AdminDoubtListResponse(total=total, doubts=items))


@router.put("/doubts/{doubt_id}/answer", response_model=CommonResponse[AnswerDoubtResponse])
async def answer_doubt(
    doubt_id: uuid.UUID,
    body: AnswerDoubtRequest,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
) -> CommonResponse[AnswerDoubtResponse]:
    doubt = (await db.execute(select(Doubt).where(Doubt.id == doubt_id))).scalar_one_or_none()
    if doubt is None:
        raise NotFoundException("Doubt not found")
    doubt.answer_text = body.answer_text
    doubt.answered_by_admin_id = admin.id
    doubt.answered_at = datetime.now(timezone.utc)
    doubt.status = "answered"
    await db.commit()
    await db.refresh(doubt)
    student = (await db.execute(select(User).where(User.id == doubt.user_id))).scalar_one_or_none()
    await enqueue(
        "task_send_doubt_answered",
        user_id=str(doubt.user_id),
        email=student.email if student else None,
        question=doubt.question_text,
        answer=body.answer_text,
    )
    return CommonResponse.ok(AnswerDoubtResponse(message="Doubt answered", notification_sent=True))


@router.put("/doubts/{doubt_id}/assign", response_model=CommonResponse[dict])
async def assign_doubt(
    doubt_id: uuid.UUID,
    body: AssignDoubtRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
) -> CommonResponse[dict]:
    doubt = (await db.execute(select(Doubt).where(Doubt.id == doubt_id))).scalar_one_or_none()
    if doubt is None:
        raise NotFoundException("Doubt not found")
    doubt.assigned_to = body.teacher_id
    await log_audit(db, admin.id, "doubt.assign", "doubt", doubt_id, {"teacher_id": str(body.teacher_id)}, request)
    await db.commit()
    return CommonResponse.ok({"assigned": True})


@router.put("/doubts/{doubt_id}/close", response_model=CommonResponse[dict])
async def close_doubt(
    doubt_id: uuid.UUID,
    body: CloseDoubtRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
) -> CommonResponse[dict]:
    doubt = (await db.execute(select(Doubt).where(Doubt.id == doubt_id))).scalar_one_or_none()
    if doubt is None:
        raise NotFoundException("Doubt not found")
    now = datetime.now(timezone.utc)
    doubt.status = "closed"
    doubt.closed_at = now
    doubt.close_reason = body.reason
    await log_audit(db, admin.id, "doubt.close", "doubt", doubt_id, {"reason": body.reason}, request)
    await db.commit()
    return CommonResponse.ok({"closed": True})


@router.post("/doubts/bulk-close", response_model=CommonResponse[dict])
async def bulk_close_doubts(
    body: BulkCloseRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
) -> CommonResponse[dict]:
    now = datetime.now(timezone.utc)
    await db.execute(
        update(Doubt)
        .where(Doubt.id.in_(body.doubt_ids))
        .values(status="closed", closed_at=now, close_reason=body.reason)
    )
    await log_audit(db, admin.id, "doubt.bulk_close", "doubt", None, {"count": len(body.doubt_ids), "reason": body.reason}, request)
    await db.commit()
    return CommonResponse.ok({"closed": len(body.doubt_ids)})


@router.get("/doubt-templates", response_model=CommonResponse[list[DoubtTemplateResponse]])
async def list_doubt_templates(
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
) -> CommonResponse[list[DoubtTemplateResponse]]:
    results = await db.execute(
        select(DoubtTemplate).where(DoubtTemplate.created_by == admin.id).order_by(DoubtTemplate.created_at.desc())
    )
    return CommonResponse.ok([DoubtTemplateResponse.model_validate(t) for t in results.scalars().all()])


@router.post("/doubt-templates", response_model=CommonResponse[DoubtTemplateResponse], status_code=status.HTTP_201_CREATED)
async def create_doubt_template(
    body: DoubtTemplateCreate,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
) -> CommonResponse[DoubtTemplateResponse]:
    tmpl = DoubtTemplate(title=body.title, body=body.body, subject_id=body.subject_id, created_by=admin.id)
    db.add(tmpl)
    await db.commit()
    await db.refresh(tmpl)
    return CommonResponse.ok(DoubtTemplateResponse.model_validate(tmpl))


@router.delete("/doubt-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_doubt_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
) -> None:
    tmpl = (await db.execute(select(DoubtTemplate).where(DoubtTemplate.id == template_id, DoubtTemplate.created_by == admin.id))).scalar_one_or_none()
    if tmpl is None:
        raise NotFoundException("Template not found")
    await db.delete(tmpl)
    await db.commit()
