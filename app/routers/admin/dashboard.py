import uuid

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.redis_client import get_redis
from app.schemas.admin import AdminDashboardResponse, ContentStatsResponse
from app.schemas.common import CommonResponse
from app.services import analytics_service

router = APIRouter(tags=["admin:dashboard"])


@router.get("/dashboard", response_model=CommonResponse[AdminDashboardResponse])
async def dashboard(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> CommonResponse[AdminDashboardResponse]:
    stats = await analytics_service.get_dashboard_stats(db)
    extended = await analytics_service.get_dashboard_extended(db, redis)
    return CommonResponse.ok(AdminDashboardResponse(**stats, **extended))


@router.get("/content/stats/{lesson_id}", response_model=CommonResponse[ContentStatsResponse])
async def get_lesson_stats(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> CommonResponse[ContentStatsResponse]:
    result = await analytics_service.get_content_stats(db, redis, lesson_id)
    return CommonResponse.ok(ContentStatsResponse(**result))
