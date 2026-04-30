"""
HTTP-level integration smoke tests.

Uses FastAPI's dependency_overrides to inject a mock DB session and bypass
JWT validation. The lifespan seed functions and Redis are patched so no
external services are required.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_current_admin, get_current_user, get_db
from app.limiter import limiter as app_rate_limiter
from app.main import app


def _noop_rate_limit(request, *args, **kwargs):
    # SlowAPI's _check_request_limit sets view_rate_limit as a side effect;
    # _inject_headers reads it. Setting it to None makes _inject_headers a no-op.
    request.state.view_rate_limit = None


@pytest.fixture
async def client(mock_db, test_user, test_admin):
    """
    AsyncClient with all external I/O patched:
    - Lifespan seed functions no-oped
    - Redis client patched (no server needed)
    - SlowAPI rate limiting bypassed (middleware + decorators)
    - check_identifier_rate_limit bypassed
    - get_db overridden with mock_db
    """
    mock_redis = AsyncMock()
    mock_redis.exists.return_value = 1
    mock_redis.set.return_value = True
    mock_redis.delete.return_value = 1

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db

    with (
        patch("app.main.seed_dev_user", new_callable=AsyncMock),
        patch("app.main.seed_content", new_callable=AsyncMock),
        patch("app.services.auth_service.redis", mock_redis),
        patch("app.routers.auth.check_identifier_rate_limit", AsyncMock()),
        # side_effect sets request.state.view_rate_limit = None so the
        # SlowAPI middleware's subsequent _inject_headers(response, None) call
        # becomes a no-op (it guards on `current_limit is not None`).
        patch.object(app_rate_limiter, "_check_request_limit", side_effect=_noop_rate_limit),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def auth_client(client, test_user, test_admin):
    """client with get_current_user and get_current_admin overridden — bypasses JWT."""
    app.dependency_overrides[get_current_user] = lambda: test_user
    app.dependency_overrides[get_current_admin] = lambda: test_admin
    yield client
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_admin, None)


# ── health check ──────────────────────────────────────────────────────────────

async def test_health_check(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ── missing auth token → 403 ──────────────────────────────────────────────────

async def test_get_me_without_token_returns_403(client):
    resp = await client.get("/api/v1/users/me")
    assert resp.status_code == 403


async def test_admin_route_without_token_returns_403(client):
    resp = await client.get("/api/v1/admin/dashboard")
    assert resp.status_code == 403


# ── admin login ───────────────────────────────────────────────────────────────

async def test_admin_login_wrong_password(client, test_admin, mock_db):
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = test_admin
    mock_db.execute.return_value = result_mock

    resp = await client.post(
        "/api/v1/auth/admin/login",
        json={"email": "admin@edyrix.in", "password": "wrong_password"},
    )
    assert resp.status_code == 401
    assert "detail" in resp.json()


async def test_admin_login_unknown_email(client, mock_db):
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = result_mock

    resp = await client.post(
        "/api/v1/auth/admin/login",
        json={"email": "nobody@edyrix.in", "password": "any_password"},
    )
    assert resp.status_code == 401


async def test_admin_login_correct_credentials(client, test_admin, mock_db):
    mock_redis = AsyncMock()
    mock_redis.set.return_value = True

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = test_admin
    mock_db.execute.return_value = result_mock

    with patch("app.services.auth_service.redis", mock_redis):
        resp = await client.post(
            "/api/v1/auth/admin/login",
            json={"email": "admin@edyrix.in", "password": "correct_password"},
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "access_token" in data
    assert data["user"]["email"] == "admin@edyrix.in"
    assert data["user"]["role"] == "super_admin"


# ── protected routes with injected auth ───────────────────────────────────────

async def test_get_me_with_auth(auth_client, test_user, mock_db):
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None  # no free trial
    mock_db.execute.return_value = result_mock

    resp = await auth_client.get("/api/v1/users/me")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["email"] == test_user.email
    assert data["role"] == "student"


async def test_logout_with_auth(auth_client, student_token, mock_db):
    token, jti = student_token

    mock_redis = AsyncMock()
    mock_redis.exists.return_value = 1
    mock_redis.delete.return_value = 1

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = MagicMock()  # user found
    mock_db.execute.return_value = result_mock

    with patch("app.services.auth_service.redis", mock_redis):
        resp = await auth_client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    assert resp.json()["data"]["message"] == "Logged out"
