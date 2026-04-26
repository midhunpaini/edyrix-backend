"""
Create or update an admin user with email + password authentication.
Run once after migrations:

    uv run python create_admin.py admin@edyrix.in <password> [role]
"""
import asyncio
import sys

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.admin import AdminUser
from app.services.auth_service import hash_password

ADMIN_ROLES = {"super_admin", "admin", "support", "content_manager"}


async def create_admin(email: str, password: str, role: str = "super_admin") -> None:
    email = email.strip().lower()
    if role not in ADMIN_ROLES:
        raise ValueError(f"role must be one of: {', '.join(sorted(ADMIN_ROLES))}")

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AdminUser).where(AdminUser.email == email))
        admin = result.scalar_one_or_none()

        if admin:
            admin.password_hash = hash_password(password)
            admin.role = role
            admin.is_active = True
            await db.commit()
            print(f"Updated admin {email} -> role={role}, password reset.")
        else:
            admin = AdminUser(
                email=email,
                name="Admin",
                role=role,
                is_active=True,
                password_hash=hash_password(password),
            )
            db.add(admin)
            await db.commit()
            print(f"Admin user created: {email}")


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        print("Usage: uv run python create_admin.py <email> <password> [role]")
        sys.exit(1)
    asyncio.run(create_admin(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) == 4 else "super_admin"))
