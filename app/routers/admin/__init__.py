from fastapi import APIRouter, Depends

from app.dependencies import require_admin
from app.routers.admin import (
    content,
    dashboard,
    doubts,
    notifications,
    revenue,
    settings,
    students,
    tests,
)

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])

router.include_router(dashboard.router)
router.include_router(students.router)
router.include_router(content.router)
router.include_router(tests.router)
router.include_router(doubts.router)
router.include_router(notifications.router)
router.include_router(revenue.router)
router.include_router(settings.router)
