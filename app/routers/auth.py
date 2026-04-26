from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.exceptions import BadRequestException, UnauthorizedException
from app.limiter import check_identifier_rate_limit, limiter
from app.models.user import FreeTrial, User
from app.schemas.common import CommonResponse, MessageResponse
from app.schemas.user import (
    AdminLoginRequest,
    AuthResponse,
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
    invalidate_token,
    store_token_jti,
    verify_firebase_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


async def _issue_token_response(user: User, is_new: bool, db: AsyncSession) -> AuthResponse:
    token, jti = create_access_token(user.id, user.role)
    await store_token_jti(jti)

    user_data = UserResponse.model_validate(user)
    trial_result = await db.execute(select(FreeTrial).where(FreeTrial.user_id == user.id))
    trial = trial_result.scalar_one_or_none()
    if trial:
        user_data.free_trial_expires_at = trial.expires_at

    return AuthResponse(access_token=token, is_new_user=is_new, user=user_data)


@router.post("/admin/login", response_model=CommonResponse[AuthResponse])
@limiter.limit("5/minute")
async def admin_login(
    request: Request,
    body: AdminLoginRequest,
    db: AsyncSession = Depends(get_db),
) -> CommonResponse[AuthResponse]:
    await check_identifier_rate_limit(f"admin_login:{body.email.lower()}", max_requests=10, window_seconds=60)
    try:
        user = await authenticate_admin(db, body.email, body.password)
    except ValueError:
        raise UnauthorizedException("Invalid email or password")
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
async def refresh_token(user: User = Depends(get_current_user)) -> CommonResponse[TokenRefreshResponse]:
    token, jti = create_access_token(user.id, user.role)
    await store_token_jti(jti)
    return CommonResponse.ok(TokenRefreshResponse(access_token=token))


@router.post("/logout", status_code=status.HTTP_200_OK, response_model=CommonResponse[MessageResponse])
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[MessageResponse]:
    auth_header = request.headers.get("Authorization", "")
    try:
        token = auth_header.removeprefix("Bearer ")
        payload = decode_access_token(token)
        jti = payload.get("jti")
        exp = payload.get("exp")
        if jti:
            expires_at = datetime.fromtimestamp(exp, tz=timezone.utc) if exp else None
            await invalidate_token(jti, db=db, expires_at=expires_at)
    except ValueError:
        pass
    return CommonResponse.ok(MessageResponse(message="Logged out"))
