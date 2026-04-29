from fastapi import APIRouter

from app.routers.student import (
    content,
    doubts,
    goals,
    payments,
    plans,
    progress,
    share,
    subscriptions,
    tests,
    users,
)

router = APIRouter()

router.include_router(content.router)
router.include_router(users.router)
router.include_router(goals.router)
router.include_router(progress.router)
router.include_router(tests.router)
router.include_router(doubts.router)
router.include_router(subscriptions.router)
router.include_router(plans.router)
router.include_router(payments.router)
router.include_router(share.router)
