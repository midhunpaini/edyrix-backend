import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.dependencies import get_db, require_admin
from app.exceptions import BadRequestException
from app.models.admin import AdminUser
from app.models.audit import AuditLog
from app.models.subscription import Plan
from app.redis_client import get_redis
from app.schemas.admin import (
    AuditLogItem,
    AuditLogListResponse,
    FeatureFlagUpdateRequest,
    SettingsResponse,
)
from app.schemas.common import CommonResponse
from app.utils.audit import log_audit
from app.utils.feature_flags import get_all_flags, is_allowed_flag, set_flag

router = APIRouter(tags=["admin:settings"])


@router.get("/settings", response_model=CommonResponse[SettingsResponse])
async def get_settings(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[SettingsResponse]:
    plans = (await db.execute(select(Plan).order_by(Plan.order_index))).scalars().all()
    flags = await get_all_flags(redis)
    admins = (await db.execute(select(AdminUser).where(AdminUser.is_active.is_(True)))).scalars().all()

    return CommonResponse.ok(SettingsResponse(
        plans=[
            {
                "id": str(p.id), "name": p.name, "slug": p.slug,
                "plan_type": p.plan_type, "billing_cycle": p.billing_cycle,
                "price_paise": p.price_paise, "is_active": p.is_active,
            }
            for p in plans
        ],
        feature_flags=flags,
        admin_users=[
            {"id": str(a.id), "name": a.name, "email": a.email, "role": a.role}
            for a in admins
        ],
    ))


@router.put("/settings/feature-flags", response_model=CommonResponse[dict])
async def update_feature_flag(
    body: FeatureFlagUpdateRequest,
    request: Request,
    redis: Redis = Depends(get_redis),
    admin: AdminUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CommonResponse[dict]:
    if not is_allowed_flag(body.flag_name):
        raise BadRequestException(f"Unknown flag: {body.flag_name}")
    await set_flag(redis, body.flag_name, body.value)
    await log_audit(db, admin.id, "settings.flag_update", "flag", None, {"flag": body.flag_name, "value": body.value}, request)
    await db.commit()
    return CommonResponse.ok({"flag": body.flag_name, "value": body.value})


@router.get("/audit-log", response_model=CommonResponse[AuditLogListResponse])
async def get_audit_log(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    action: str | None = Query(None),
    admin_id: uuid.UUID | None = Query(None),
    resource_type: str | None = Query(None),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[AuditLogListResponse]:
    offset = (page - 1) * limit

    AuditAdmin = aliased(AdminUser)
    base_q = select(AuditLog, AuditAdmin).outerjoin(AuditAdmin, AuditLog.admin_id == AuditAdmin.id)

    if action:
        base_q = base_q.where(AuditLog.action.ilike(f"%{action}%"))
    if admin_id:
        base_q = base_q.where(AuditLog.admin_id == admin_id)
    if resource_type:
        base_q = base_q.where(AuditLog.resource_type == resource_type)
    if from_date:
        base_q = base_q.where(AuditLog.created_at >= datetime.fromisoformat(from_date))
    if to_date:
        base_q = base_q.where(AuditLog.created_at <= datetime.fromisoformat(to_date))

    total = (await db.execute(select(func.count()).select_from(base_q.subquery()))).scalar() or 0
    rows = (await db.execute(base_q.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset))).all()

    items = [
        AuditLogItem(
            id=log.id,
            admin_name=admin.name if admin else None,
            action=log.action,
            resource_type=log.resource_type,
            resource_id=log.resource_id,
            changes=log.changes,
            ip_address=log.ip_address,
            created_at=log.created_at,
        )
        for log, admin in rows
    ]
    return CommonResponse.ok(AuditLogListResponse(total=total, logs=items))
