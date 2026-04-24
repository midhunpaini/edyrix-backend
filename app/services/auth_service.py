import uuid
from datetime import datetime, timedelta, timezone

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import FreeTrial, User
from app.redis_client import redis


def _ensure_firebase() -> None:
    if firebase_admin._apps:
        return
    private_key = settings.FIREBASE_PRIVATE_KEY
    # Normalise: strip surrounding quotes pydantic-settings might preserve,
    # then ensure literal \n sequences become real newlines.
    private_key = private_key.strip("\"'")
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


def verify_firebase_token(firebase_token: str) -> dict:
    _ensure_firebase()
    try:
        decoded = firebase_auth.verify_id_token(firebase_token)
        return decoded
    except Exception:
        raise ValueError("Invalid Firebase token")


def create_access_token(user_id: uuid.UUID, role: str) -> tuple[str, str]:
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


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        return payload
    except JWTError:
        raise ValueError("Invalid or expired token")


async def store_token_jti(jti: str) -> None:
    ttl = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    await redis.set(f"jwt:{jti}", "1", ex=ttl)


async def is_token_valid(jti: str) -> bool:
    return await redis.exists(f"jwt:{jti}") == 1


async def invalidate_token(jti: str) -> None:
    await redis.delete(f"jwt:{jti}")


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
    is_new = False

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

        trial = FreeTrial(user_id=user.id)
        db.add(trial)
        await db.commit()
        await db.refresh(user)
        is_new = True
    else:
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

    return user, is_new
