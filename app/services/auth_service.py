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
from app.models.user import FreeTrial, User
from app.redis_client import redis

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


async def authenticate_admin(db: AsyncSession, email: str, password: str) -> User:
    result = await db.execute(
        select(User).where(
            User.email == email,
            User.role == "admin",
            User.is_active.is_(True),
        )
    )
    user = result.scalar_one_or_none()
    if user is None or user.password_hash is None or not verify_password(password, user.password_hash):
        raise ValueError("Invalid credentials")
    return user


def _ensure_firebase() -> None:
    """Initialize the Firebase Admin SDK if not already done."""
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
    """Verify a Firebase ID token and return its decoded claims."""
    _ensure_firebase()
    try:
        return firebase_auth.verify_id_token(firebase_token)
    except (fb_exceptions.FirebaseError, ValueError) as exc:
        raise ValueError("Invalid Firebase token") from exc


def create_access_token(user_id: uuid.UUID, role: str) -> tuple[str, str]:
    """Create a signed JWT and return (token, jti)."""
    jti = str(uuid.uuid4())
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "role": role,
        "jti": jti,
        "exp": expire,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    return token, jti


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT, raising ValueError on failure."""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except JWTError as exc:
        raise ValueError("Invalid or expired token") from exc


async def store_token_jti(jti: str) -> None:
    """Persist a JTI in Redis so the token can be validated and revoked."""
    ttl = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    await redis.set(f"jwt:{jti}", "1", ex=ttl)


async def is_token_valid(jti: str) -> bool:
    """Return True if the JTI is still present in Redis (not revoked)."""
    return await redis.exists(f"jwt:{jti}") == 1


async def invalidate_token(jti: str) -> None:
    """Remove a JTI from Redis, effectively revoking the token."""
    await redis.delete(f"jwt:{jti}")


async def get_or_create_user(
    db: AsyncSession,
    firebase_uid: str,
    email: str | None,
    phone: str | None,
    name: str,
    avatar_url: str | None,
) -> tuple[User, bool]:
    """Fetch an existing user or create a new one with a 7-day free trial."""
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
