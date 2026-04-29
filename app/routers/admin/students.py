import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_admin
from app.exceptions import NotFoundException
from app.models.admin import AdminUser
from app.models.subscription import Plan, Subscription
from app.models.user import User
from app.schemas.admin import (
    AdminStudentItem,
    AdminStudentListResponse,
    GrantAccessRequest,
    GrantAccessResponse,
    StudentDetailResponse,
    SuspendRequest,
)
from app.schemas.common import CommonResponse
from app.services import student_service
from app.utils.audit import log_audit

router = APIRouter(prefix="/students", tags=["admin:students"])


@router.get("", response_model=CommonResponse[AdminStudentListResponse])
async def list_students(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    class_number: int | None = Query(None),
    subscription_status: Literal["active", "trial", "free"] | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[AdminStudentListResponse]:
    total, items = await student_service.list_students(db, page, limit, search, class_number, subscription_status)
    return CommonResponse.ok(AdminStudentListResponse(
        total=total,
        students=[AdminStudentItem(**item) for item in items],
    ))


@router.get("/export")
async def export_students(
    class_number: int | None = Query(None),
    subscription_status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> StreamingResponse:
    csv_content = await student_service.export_students_csv(db, class_number, subscription_status)
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=edyrix_students.csv"},
    )


@router.get("/{student_id}", response_model=CommonResponse[StudentDetailResponse])
async def get_student_detail(
    student_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[StudentDetailResponse]:
    detail = await student_service.get_student_detail(db, student_id)
    return CommonResponse.ok(StudentDetailResponse(**detail))


@router.post("/{student_id}/grant-access", response_model=CommonResponse[GrantAccessResponse], status_code=status.HTTP_201_CREATED)
async def grant_student_access(
    student_id: uuid.UUID,
    body: GrantAccessRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
) -> CommonResponse[GrantAccessResponse]:
    user = (await db.execute(select(User).where(User.id == student_id))).scalar_one_or_none()
    if user is None:
        raise NotFoundException("Student not found")
    plan = (await db.execute(select(Plan).where(Plan.id == body.plan_id, Plan.is_active.is_(True)))).scalar_one_or_none()
    if plan is None:
        raise NotFoundException("Plan not found")

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=body.duration_days)
    sub = Subscription(
        user_id=student_id,
        plan_id=body.plan_id,
        status="active",
        started_at=now,
        expires_at=expires_at,
        auto_renew=False,
    )
    db.add(sub)
    await log_audit(db, admin.id, "student.grant_access", "student", student_id,
                    {"plan_id": str(body.plan_id), "duration_days": body.duration_days, "reason": body.reason}, request)
    await db.commit()
    await db.refresh(sub)
    return CommonResponse.ok(GrantAccessResponse(subscription_id=sub.id, expires_at=sub.expires_at))


@router.post("/{student_id}/revoke-access", response_model=CommonResponse[dict])
async def revoke_student_access(
    student_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
) -> CommonResponse[dict]:
    now = datetime.now(timezone.utc)
    await db.execute(
        update(Subscription)
        .where(Subscription.user_id == student_id, Subscription.status == "active")
        .values(status="cancelled", cancelled_at=now)
    )
    await log_audit(db, admin.id, "student.revoke_access", "student", student_id, {}, request)
    await db.commit()
    return CommonResponse.ok({"revoked": True})


@router.put("/{student_id}/suspend", response_model=CommonResponse[dict])
async def suspend_student(
    student_id: uuid.UUID,
    body: SuspendRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
) -> CommonResponse[dict]:
    now = datetime.now(timezone.utc)
    user = (await db.execute(select(User).where(User.id == student_id))).scalar_one_or_none()
    if user is None:
        raise NotFoundException("Student not found")
    user.is_suspended = True
    user.suspended_at = now
    user.suspended_reason = body.reason
    await log_audit(db, admin.id, "student.suspend", "student", student_id, {"reason": body.reason}, request)
    await db.commit()
    return CommonResponse.ok({"suspended": True})


@router.put("/{student_id}/unsuspend", response_model=CommonResponse[dict])
async def unsuspend_student(
    student_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
) -> CommonResponse[dict]:
    user = (await db.execute(select(User).where(User.id == student_id))).scalar_one_or_none()
    if user is None:
        raise NotFoundException("Student not found")
    user.is_suspended = False
    user.suspended_at = None
    user.suspended_reason = None
    await log_audit(db, admin.id, "student.unsuspend", "student", student_id, {}, request)
    await db.commit()
    return CommonResponse.ok({"suspended": False})
