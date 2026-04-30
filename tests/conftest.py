import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

# ── Must set ALL required env vars before any app module is imported ───────────
# pydantic-settings reads os.environ first (highest priority), then .env file.
os.environ.setdefault("SECRET_KEY", "test-secret-key-minimum-32-characters!!!")
os.environ.setdefault("POSTGRES_SERVER", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_DB", "edyrix_test")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("FIREBASE_PROJECT_ID", "test-project")
os.environ.setdefault("FIREBASE_PRIVATE_KEY", "test-key")
os.environ.setdefault("FIREBASE_CLIENT_EMAIL", "test@test-project.iam.gserviceaccount.com")
os.environ.setdefault("RAZORPAY_KEY_ID", "rzp_test_xxx")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "test_razorpay_secret")
os.environ.setdefault("RAZORPAY_WEBHOOK_SECRET", "test_webhook_secret")
os.environ.setdefault("R2_ACCOUNT_ID", "test_account")
os.environ.setdefault("R2_ACCESS_KEY_ID", "test_r2_key")
os.environ.setdefault("R2_SECRET_ACCESS_KEY", "test_r2_secret")
os.environ.setdefault("R2_PUBLIC_URL", "https://test.r2.dev")
os.environ.setdefault("RESEND_API_KEY", "re_test_xxx")

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import AdminUser
from app.models.user import User
from app.services.auth_service import create_access_token, hash_password


@pytest.fixture
def mock_redis() -> AsyncMock:
    """AsyncMock for the Redis client. Default: JTI present (token valid)."""
    mock = AsyncMock()
    mock.exists.return_value = 1
    mock.set.return_value = True
    mock.delete.return_value = 1
    mock.incr.return_value = 1
    mock.expire.return_value = True
    return mock


@pytest.fixture
def mock_db() -> AsyncMock:
    """AsyncMock for AsyncSession. Tests configure execute() return values as needed."""
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture
def test_user() -> User:
    """Valid active student User (not persisted — uses SQLAlchemy constructor)."""
    user = User(
        firebase_uid="test_firebase_uid",
        email="student@example.com",
        phone=None,
        name="Test Student",
        role="student",
        current_class=10,
        medium="english",
        is_active=True,
        is_suspended=False,
        onboarding_complete=True,
        exam_date=None,
    )
    user.id = uuid.uuid4()
    # SQLAlchemy column default=_utcnow fires at insert time, not on construction
    user.created_at = datetime.now(timezone.utc)
    return user


@pytest.fixture
def test_admin() -> AdminUser:
    """Valid active AdminUser with a known password (not persisted)."""
    admin = AdminUser(
        email="admin@edyrix.in",
        name="Test Admin",
        password_hash=hash_password("correct_password"),
        role="super_admin",
        is_active=True,
    )
    admin.id = uuid.uuid4()
    admin.created_at = datetime.now(timezone.utc)
    return admin


@pytest.fixture
def student_token(test_user: User) -> tuple[str, str]:
    """Returns (jwt_string, jti) for the test student user."""
    return create_access_token(test_user.id, "student", token_type="student")


@pytest.fixture
def admin_token(test_admin: AdminUser) -> tuple[str, str]:
    """Returns (jwt_string, jti) for the test admin user."""
    return create_access_token(test_admin.id, "super_admin", token_type="admin")
