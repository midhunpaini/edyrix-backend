from typing import AsyncGenerator

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.exceptions import UnauthorizedException
from app.models.admin import AdminUser
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
    token_type: str | None = payload.get("typ")

    if not jti or not user_id or token_type != "student":
        raise UnauthorizedException("Invalid token payload")

    if not await is_token_valid(jti, db):
        raise UnauthorizedException("Token has been revoked")

    result = await db.execute(
        select(User).where(User.id == user_id, User.role == "student", User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise UnauthorizedException("User not found")

    return user


async def get_current_admin(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> AdminUser:
    token = credentials.credentials

    try:
        payload = decode_access_token(token)
    except ValueError:
        raise UnauthorizedException("Invalid token")

    jti: str | None = payload.get("jti")
    admin_id: str | None = payload.get("sub")
    token_type: str | None = payload.get("typ")

    if not jti or not admin_id or token_type != "admin":
        raise UnauthorizedException("Invalid token payload")

    if not await is_token_valid(jti, db):
        raise UnauthorizedException("Token has been revoked")

    result = await db.execute(select(AdminUser).where(AdminUser.id == admin_id, AdminUser.is_active.is_(True)))
    admin = result.scalar_one_or_none()
    if admin is None:
        raise UnauthorizedException("Admin not found")

    return admin


async def require_admin(admin: AdminUser = Depends(get_current_admin)) -> AdminUser:
    return admin
