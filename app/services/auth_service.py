import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials, exceptions as fb_exceptions
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.auth import TokenBlacklist
from app.models.admin import AdminUser
from app.models.user import FreeTrial, User
from app.redis_client import redis

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


async def authenticate_admin(db: AsyncSession, email: str, password: str) -> AdminUser:
    result = await db.execute(
        select(AdminUser).where(
            AdminUser.email == email.strip().lower(),
            AdminUser.is_active.is_(True),
        )
    )
    admin = result.scalar_one_or_none()
    if admin is None or not verify_password(password, admin.password_hash):
        raise ValueError("Invalid credentials")
    return admin


def _ensure_firebase() -> None:
    try:
        firebase_admin.get_app()
    except ValueError:
        private_key = settings.FIREBASE_PRIVATE_KEY.strip("\"'")
        if "\\n" in private_key:
            private_key = private_key.replace("\\n", "\n")
        cred = credentials.Certificate(
            {
                "type": "service_account",
                "project_id": settings.FIREBASE_PROJECT_ID,
                "private_key_id": "key",
                "private_key": private_key,
                "client_email": settings.FIREBASE_CLIENT_EMAIL,
                "client_id": "",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": "",
            }
        )
        firebase_admin.initialize_app(cred)


def verify_firebase_token(firebase_token: str) -> dict[str, Any]:
    _ensure_firebase()
    try:
        return firebase_auth.verify_id_token(firebase_token)
    except (fb_exceptions.FirebaseError, ValueError) as exc:
        raise ValueError("Invalid Firebase token") from exc


def create_access_token(user_id: uuid.UUID, role: str, token_type: str = "student") -> tuple[str, str]:
    jti = str(uuid.uuid4())
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "role": role,
        "typ": token_type,
        "jti": jti,
        "exp": expire,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    return token, jti


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except JWTError as exc:
        raise ValueError("Invalid or expired token") from exc


async def store_token_jti(jti: str) -> None:
    ttl = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    await redis.set(f"jwt:{jti}", "1", ex=ttl)


async def is_token_valid(jti: str, db: AsyncSession | None = None) -> bool:
    # Fast path: JTI present in Redis → valid
    if await redis.exists(f"jwt:{jti}") == 1:
        return True
    # Redis miss: check DB blacklist for explicit revocations.
    # If the JTI was deliberately revoked, it will be in the blacklist.
    # If it merely expired from Redis, it's also invalid — JWT expiry enforced by decode_access_token.
    if db is not None:
        result = await db.execute(select(TokenBlacklist).where(TokenBlacklist.jti == jti))
        if result.scalar_one_or_none() is not None:
            return False
    # Not in Redis, not blacklisted: optimistically trust JWT signature + expiry
    return True


async def invalidate_token(
    jti: str,
    db: AsyncSession | None = None,
    expires_at: datetime | None = None,
) -> None:
    await redis.delete(f"jwt:{jti}")
    if db is not None and expires_at is not None:
        db.add(TokenBlacklist(jti=jti, expires_at=expires_at))
        await db.commit()


async def get_or_create_user(
    db: AsyncSession,
    firebase_uid: str,
    email: str | None,
    phone: str | None,
    name: str,
    avatar_url: str | None,
) -> tuple[User, bool]:
    result = await db.execute(select(User).where(User.firebase_uid == firebase_uid))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            firebase_uid=firebase_uid,
            email=email,
            phone=phone,
            name=name,
            avatar_url=avatar_url,
            role="student",
        )
        db.add(user)
        await db.flush()
        db.add(FreeTrial(user_id=user.id))
        await db.commit()
        await db.refresh(user)
        return user, True

    if email and not user.email:
        user.email = email
    if phone and not user.phone:
        user.phone = phone
    if avatar_url and not user.avatar_url:
        user.avatar_url = avatar_url
    if name and user.name != name:
        user.name = name
    await db.commit()
    await db.refresh(user)
    return user, False
