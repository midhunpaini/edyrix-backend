from passlib.context import CryptContext
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.logger import logger
from app.models.user import FreeTrial, User

DEV_EMAIL = "midhunpk2@gmail.com"
DEV_PASSWORD = "asd123.."
DEV_FIREBASE_UID = "dev:midhunpk2@gmail.com"

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


async def seed_dev_user() -> None:
    if settings.APP_ENV != "development":
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == DEV_EMAIL))
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                firebase_uid=DEV_FIREBASE_UID,
                email=DEV_EMAIL,
                name="Midhun PK",
                role="student",
                current_class=10,
                medium="english",
                is_active=True,
                password_hash=hash_password(DEV_PASSWORD),
            )
            db.add(user)
            await db.flush()
            db.add(FreeTrial(user_id=user.id))
            await db.commit()
            logger.info("Development user seeded: %s", DEV_EMAIL)
            return

        user.name = user.name or "Midhun PK"
        user.firebase_uid = user.firebase_uid or DEV_FIREBASE_UID
        user.role = "student"
        user.current_class = user.current_class or 10
        user.medium = user.medium or "english"
        user.is_active = True
        user.password_hash = hash_password(DEV_PASSWORD)

        trial_result = await db.execute(select(FreeTrial).where(FreeTrial.user_id == user.id))
        if trial_result.scalar_one_or_none() is None:
            db.add(FreeTrial(user_id=user.id))

        await db.commit()
        logger.info("Development user ensured: %s", DEV_EMAIL)
