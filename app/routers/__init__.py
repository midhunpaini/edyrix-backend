from fastapi import APIRouter

from app.routers import auth, webhooks
from app.routers.admin import router as admin_router
from app.routers.student import router as student_router

router = APIRouter()

router.include_router(auth.router)
router.include_router(webhooks.router)
router.include_router(student_router)
router.include_router(admin_router)
