from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.exceptions import BadRequestException, ConflictException, ForbiddenException, UnauthorizedException
from app.limiter import check_identifier_rate_limit, limiter
from app.models.admin import AdminUser
from app.models.user import FreeTrial, User
from app.schemas.common import CommonResponse, MessageResponse
from app.schemas.user import (
    AdminAuthResponse,
    AdminLoginRequest,
    AdminUserResponse,
    AuthResponse,
    CreateAdminRequest,
    FirebaseGoogleRequest,
    PhoneSendOTPRequest,
    PhoneVerifyRequest,
    TokenRefreshResponse,
    UserResponse,
)
from app.services.auth_service import (
    authenticate_admin,
    create_access_token,
    decode_access_token,
    get_or_create_user,
    hash_password,
    invalidate_token,
    is_token_valid,
    store_token_jti,
    verify_firebase_token,
)
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])
bearer_scheme = HTTPBearer()


async def _issue_token_response(user: User, is_new: bool, db: AsyncSession) -> AuthResponse:
    token, jti = create_access_token(user.id, "student", token_type="student")
    await store_token_jti(jti)

    user_data = UserResponse.model_validate(user)
    trial_result = await db.execute(select(FreeTrial).where(FreeTrial.user_id == user.id))
    trial = trial_result.scalar_one_or_none()
    if trial:
        user_data.free_trial_expires_at = trial.expires_at

    return AuthResponse(access_token=token, is_new_user=is_new, user=user_data)


async def _issue_admin_token_response(admin: AdminUser) -> AdminAuthResponse:
    token, jti = create_access_token(admin.id, admin.role, token_type="admin")
    await store_token_jti(jti)
    return AdminAuthResponse(access_token=token, user=AdminUserResponse.model_validate(admin))


@router.post("/admin/login", response_model=CommonResponse[AdminAuthResponse])
@limiter.limit("5/minute")
async def admin_login(
    request: Request,
    body: AdminLoginRequest,
    db: AsyncSession = Depends(get_db),
) -> CommonResponse[AuthResponse]:
    await check_identifier_rate_limit(f"admin_login:{body.email.lower()}", max_requests=10, window_seconds=60)
    try:
        admin = await authenticate_admin(db, body.email, body.password)
    except ValueError:
        raise UnauthorizedException("Invalid email or password")
    return CommonResponse.ok(await _issue_admin_token_response(admin))


@router.post("/admin/create", response_model=CommonResponse[AdminUserResponse], status_code=status.HTTP_201_CREATED)
async def create_admin(
    body: CreateAdminRequest,
    db: AsyncSession = Depends(get_db),
) -> CommonResponse[UserResponse]:
    if settings.APP_ENV != "development":
        raise ForbiddenException("Not available in production")

    email = body.email.strip().lower()
    if not email:
        raise BadRequestException("Email is required")

    existing_email = await db.execute(select(AdminUser).where(AdminUser.email == email))
    if existing_email.scalar_one_or_none() is not None:
        raise ConflictException("Email already exists")

    admin = AdminUser(
        email=email,
        name=(body.name or "Admin").strip() or "Admin",
        role=body.role,
        is_active=True,
        password_hash=hash_password(body.password),
    )
    db.add(admin)
    await db.commit()
    await db.refresh(admin)
    return CommonResponse.ok(AdminUserResponse.model_validate(admin), "Admin created")


class _DevLoginRequest(BaseModel):
    email: str


@router.post("/dev-login", response_model=CommonResponse[AuthResponse])
async def dev_login(
    body: _DevLoginRequest,
    db: AsyncSession = Depends(get_db),
) -> CommonResponse[AuthResponse]:
    if settings.APP_ENV != "development":
        raise ForbiddenException("Not available in production")
    result = await db.execute(
        select(User).where(User.email == body.email, User.role == "student", User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise BadRequestException(f"No active user found with email {body.email}")
    return CommonResponse.ok(await _issue_token_response(user, False, db))


@router.post("/google", response_model=CommonResponse[AuthResponse])
@limiter.limit("10/minute")
async def google_login(
    request: Request,
    body: FirebaseGoogleRequest,
    db: AsyncSession = Depends(get_db),
) -> CommonResponse[AuthResponse]:
    try:
        decoded = verify_firebase_token(body.firebase_token)
    except ValueError:
        raise UnauthorizedException("Invalid Firebase token")

    uid = decoded.get("uid")
    email = decoded.get("email")
    name = decoded.get("name") or decoded.get("email", "").split("@")[0]
    avatar_url = decoded.get("picture")

    if not uid:
        raise BadRequestException("Firebase token missing uid")

    user, is_new = await get_or_create_user(
        db,
        firebase_uid=uid,
        email=email,
        phone=None,
        name=name,
        avatar_url=avatar_url,
    )
    return CommonResponse.ok(await _issue_token_response(user, is_new, db))


@router.post("/phone/send-otp", status_code=status.HTTP_200_OK, response_model=CommonResponse[MessageResponse])
@limiter.limit("3/minute")
async def send_otp(request: Request, body: PhoneSendOTPRequest) -> CommonResponse[MessageResponse]:
    await check_identifier_rate_limit(f"otp_send:{body.phone}", max_requests=5, window_seconds=300)
    return CommonResponse.ok(MessageResponse(message="OTP sent"))


@router.post("/phone/verify", response_model=CommonResponse[AuthResponse])
@limiter.limit("5/minute")
async def phone_verify(
    request: Request,
    body: PhoneVerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> CommonResponse[AuthResponse]:
    await check_identifier_rate_limit(f"otp_verify:{body.phone}", max_requests=10, window_seconds=300)
    try:
        decoded = verify_firebase_token(body.firebase_token)
    except ValueError:
        raise UnauthorizedException("Invalid Firebase token")

    uid = decoded.get("uid")
    phone = decoded.get("phone_number") or body.phone

    if not uid:
        raise BadRequestException("Firebase token missing uid")

    name = phone.replace("+91", "") if phone else "Student"

    user, is_new = await get_or_create_user(
        db,
        firebase_uid=uid,
        email=None,
        phone=phone,
        name=name,
        avatar_url=None,
    )
    return CommonResponse.ok(await _issue_token_response(user, is_new, db))


@router.post("/refresh", response_model=CommonResponse[TokenRefreshResponse])
async def refresh_token(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> CommonResponse[TokenRefreshResponse]:
    payload = await _validate_refreshable_principal(credentials.credentials, db)
    token, jti = create_access_token(payload["subject_id"], payload["role"], token_type=payload["token_type"])
    await store_token_jti(jti)
    return CommonResponse.ok(TokenRefreshResponse(access_token=token))


@router.post("/logout", status_code=status.HTTP_200_OK, response_model=CommonResponse[MessageResponse])
async def logout(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> CommonResponse[MessageResponse]:
    try:
        token = credentials.credentials
        await _validate_refreshable_principal(token, db)
        payload = decode_access_token(token)
        jti = payload.get("jti")
        exp = payload.get("exp")
        if jti:
            expires_at = datetime.fromtimestamp(exp, tz=timezone.utc) if exp else None
            await invalidate_token(jti, db=db, expires_at=expires_at)
    except ValueError:
        pass
    return CommonResponse.ok(MessageResponse(message="Logged out"))


async def _validate_refreshable_principal(token: str, db: AsyncSession) -> dict[str, str]:
    try:
        payload = decode_access_token(token)
    except ValueError:
        raise UnauthorizedException("Invalid token")

    jti: str | None = payload.get("jti")
    subject_id: str | None = payload.get("sub")
    token_type: str | None = payload.get("typ")
    role: str | None = payload.get("role")

    if not jti or not subject_id or token_type not in ("student", "admin") or not role:
        raise UnauthorizedException("Invalid token payload")

    if not await is_token_valid(jti, db):
        raise UnauthorizedException("Token has been revoked")

    if token_type == "admin":
        result = await db.execute(select(AdminUser).where(AdminUser.id == subject_id, AdminUser.is_active.is_(True)))
        admin = result.scalar_one_or_none()
        if admin is None:
            raise UnauthorizedException("Admin not found")
        return {"subject_id": str(admin.id), "role": admin.role, "token_type": "admin"}

    result = await db.execute(
        select(User).where(User.id == subject_id, User.role == "student", User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise UnauthorizedException("User not found")
    return {"subject_id": str(user.id), "role": "student", "token_type": "student"}
