"""
Unit tests for auth_service: JWT, password hashing, token revocation, admin auth.

Redis and DB calls are patched with AsyncMock so these tests run without
any external services.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jose import jwt

from app.config import settings
from app.services.auth_service import (
    authenticate_admin,
    create_access_token,
    decode_access_token,
    hash_password,
    is_token_valid,
    verify_password,
)


# ── password hashing ──────────────────────────────────────────────────────────

def test_hash_is_not_plaintext():
    pw = "hunter2"
    assert hash_password(pw) != pw


def test_correct_password_verifies():
    pw = "correct_password_123!"
    assert verify_password(pw, hash_password(pw))


def test_wrong_password_fails():
    hashed = hash_password("correct")
    assert not verify_password("wrong", hashed)


def test_hash_is_different_each_call():
    pw = "same_password"
    assert hash_password(pw) != hash_password(pw)


# ── JWT create / decode ───────────────────────────────────────────────────────

def test_student_token_payload():
    uid = uuid.uuid4()
    token, jti = create_access_token(uid, "student", token_type="student")
    p = decode_access_token(token)

    assert p["sub"] == str(uid)
    assert p["typ"] == "student"
    assert p["role"] == "student"
    assert p["jti"] == jti


def test_admin_token_payload():
    admin_id = uuid.uuid4()
    token, jti = create_access_token(admin_id, "super_admin", token_type="admin")
    p = decode_access_token(token)

    assert p["sub"] == str(admin_id)
    assert p["typ"] == "admin"
    assert p["role"] == "super_admin"
    assert p["jti"] == jti


def test_student_and_admin_tokens_have_distinct_typ():
    uid = uuid.uuid4()
    s_token, _ = create_access_token(uid, "student", token_type="student")
    a_token, _ = create_access_token(uid, "super_admin", token_type="admin")
    assert decode_access_token(s_token)["typ"] == "student"
    assert decode_access_token(a_token)["typ"] == "admin"


def test_each_token_has_unique_jti():
    uid = uuid.uuid4()
    _, jti1 = create_access_token(uid, "student", token_type="student")
    _, jti2 = create_access_token(uid, "student", token_type="student")
    assert jti1 != jti2


def test_decode_garbage_raises():
    with pytest.raises(ValueError, match="Invalid or expired token"):
        decode_access_token("not.a.token")


def test_decode_wrong_secret_raises():
    payload = {
        "sub": str(uuid.uuid4()),
        "role": "student",
        "typ": "student",
        "jti": str(uuid.uuid4()),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    bad_token = jwt.encode(payload, "wrong-secret", algorithm="HS256")
    with pytest.raises(ValueError):
        decode_access_token(bad_token)


def test_decode_expired_token_raises():
    payload = {
        "sub": str(uuid.uuid4()),
        "role": "student",
        "typ": "student",
        "jti": str(uuid.uuid4()),
        "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
    }
    expired_token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    with pytest.raises(ValueError):
        decode_access_token(expired_token)


# ── is_token_valid ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_token_valid_when_jti_in_redis(mock_redis, mock_db):
    jti = str(uuid.uuid4())
    mock_redis.exists.return_value = 1

    with patch("app.services.auth_service.redis", mock_redis):
        assert await is_token_valid(jti, db=mock_db) is True

    mock_redis.exists.assert_called_once_with(f"jwt:{jti}")


@pytest.mark.asyncio
async def test_token_invalid_when_blacklisted(mock_redis, mock_db):
    jti = str(uuid.uuid4())
    mock_redis.exists.return_value = 0  # not in Redis

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = MagicMock()  # blacklist entry found
    mock_db.execute.return_value = result_mock

    with patch("app.services.auth_service.redis", mock_redis):
        assert await is_token_valid(jti, db=mock_db) is False


@pytest.mark.asyncio
async def test_token_trusted_when_not_in_redis_and_not_blacklisted(mock_redis, mock_db):
    jti = str(uuid.uuid4())
    mock_redis.exists.return_value = 0  # Redis miss

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None  # not in blacklist
    mock_db.execute.return_value = result_mock

    with patch("app.services.auth_service.redis", mock_redis):
        assert await is_token_valid(jti, db=mock_db) is True


@pytest.mark.asyncio
async def test_is_token_valid_without_db_trusts_jwt(mock_redis):
    jti = str(uuid.uuid4())
    mock_redis.exists.return_value = 0  # Redis miss, no DB passed

    with patch("app.services.auth_service.redis", mock_redis):
        # Without a db argument we fall through to trusting the JWT signature/expiry
        assert await is_token_valid(jti) is True


# ── authenticate_admin ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_authenticate_admin_correct_password(test_admin, mock_db):
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = test_admin
    mock_db.execute.return_value = result_mock

    admin = await authenticate_admin(mock_db, "admin@edyrix.in", "correct_password")
    assert admin is test_admin


@pytest.mark.asyncio
async def test_authenticate_admin_wrong_password(test_admin, mock_db):
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = test_admin
    mock_db.execute.return_value = result_mock

    with pytest.raises(ValueError, match="Invalid credentials"):
        await authenticate_admin(mock_db, "admin@edyrix.in", "wrong_password")


@pytest.mark.asyncio
async def test_authenticate_admin_email_not_found(mock_db):
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = result_mock

    with pytest.raises(ValueError, match="Invalid credentials"):
        await authenticate_admin(mock_db, "nobody@edyrix.in", "any_password")


@pytest.mark.asyncio
async def test_authenticate_admin_email_normalised(test_admin, mock_db):
    """Email lookup is case-insensitive (auth_service strips + lowercases)."""
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = test_admin
    mock_db.execute.return_value = result_mock

    admin = await authenticate_admin(mock_db, "  ADMIN@EDYRIX.IN  ", "correct_password")
    assert admin is test_admin
