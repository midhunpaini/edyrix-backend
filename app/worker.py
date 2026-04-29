"""
arq background worker. Run with:
    python -m arq app.worker.WorkerSettings
"""
from datetime import datetime, timezone
from urllib.parse import urlparse

from arq.connections import RedisSettings
from arq.cron import cron
from sqlalchemy import delete, select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.auth import TokenBlacklist
from app.services.email_service import send_doubt_answered_email
from app.services import notification_service


# ── Task functions ─────────────────────────────────────────────────────────────

async def task_send_doubt_answered(
    ctx,
    *,
    user_id: str,
    email: str | None,
    question: str,
    answer: str,
) -> None:
    async with AsyncSessionLocal() as db:
        await notification_service.send_doubt_answered(db, user_id, question)
    if email:
        await send_doubt_answered_email(email, question, answer)


async def task_cleanup_blacklist(ctx) -> None:
    """Purge expired rows from token_blacklist — runs nightly."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(TokenBlacklist).where(TokenBlacklist.expires_at < datetime.now(timezone.utc))
        )
        await db.commit()


async def task_expire_subscriptions(ctx) -> None:
    """Mark overdue active subscriptions as expired — runs every hour."""
    from sqlalchemy import update
    from app.models.subscription import Subscription

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Subscription)
            .where(
                Subscription.status == "active",
                Subscription.expires_at < now,
                Subscription.expires_at.isnot(None),
            )
            .values(status="expired")
        )
        await db.commit()


# ── Worker settings ────────────────────────────────────────────────────────────

def _redis_settings() -> RedisSettings:
    url = urlparse(settings.REDIS_URL)
    return RedisSettings(
        host=url.hostname or "localhost",
        port=url.port or 6379,
        database=int(url.path.lstrip("/") or 0),
        password=url.password,
    )


class WorkerSettings:
    redis_settings = _redis_settings()
    functions = [task_send_doubt_answered]
    cron_jobs = [
        cron(task_cleanup_blacklist, hour={3}, minute={0}),
        cron(task_expire_subscriptions, minute={0}),  # every hour
    ]
    max_jobs = 10
    job_timeout = 30
