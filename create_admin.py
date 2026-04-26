"""
Create or update an admin user with email + password authentication.
Run once after migrations:

    uv run python create_admin.py admin@edyrix.in <password>
"""
import asyncio
import sys

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.user import User
from app.services.auth_service import hash_password


async def create_admin(email: str, password: str) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if user:
            user.password_hash = hash_password(password)
            user.role = "admin"
            await db.commit()
            print(f"Updated {email} → role=admin, password reset.")
        else:
            user = User(
                firebase_uid=None,
                email=email,
                name="Admin",
                role="admin",
                password_hash=hash_password(password),
            )
            db.add(user)
            await db.commit()
            print(f"Admin user created: {email}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: uv run python create_admin.py <email> <password>")
        sys.exit(1)
    asyncio.run(create_admin(sys.argv[1], sys.argv[2]))
