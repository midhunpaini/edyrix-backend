from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.exceptions import ForbiddenException, UnauthorizedException
from app.models.subscription import Subscription
from app.models.user import User
from app.services.auth_service import decode_access_token, is_token_valid

bearer_scheme = HTTPBearer()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials

    try:
        payload = decode_access_token(token)
    except ValueError:
        raise UnauthorizedException("Invalid token")

    jti: str | None = payload.get("jti")
    user_id: str | None = payload.get("sub")

    if not jti or not user_id:
        raise UnauthorizedException("Invalid token payload")

    if not await is_token_valid(jti, db):
        raise UnauthorizedException("Token has been revoked")

    result = await db.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
    user = result.scalar_one_or_none()

    if user is None:
        raise UnauthorizedException("User not found")

    await _expire_old_subscriptions(db, user)

    return user


async def _expire_old_subscriptions(db: AsyncSession, user: User) -> None:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.status == "active",
            Subscription.expires_at < now,
            Subscription.expires_at.isnot(None),
        )
    )
    expired = result.scalars().all()
    if expired:
        for sub in expired:
            sub.status = "expired"
        await db.commit()


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise ForbiddenException("Admin access required")
    return user
