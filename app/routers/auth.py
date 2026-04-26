from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import FreeTrial, User
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


@router.post("/admin/login", response_model=AuthResponse)
async def admin_login(
    body: AdminLoginRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    try:
        user = await authenticate_admin(db, body.email, body.password)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    return await _issue_token_response(user, False, db)


@router.post("/google", response_model=AuthResponse)
async def google_login(
    body: FirebaseGoogleRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    try:
        decoded = verify_firebase_token(body.firebase_token)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Firebase token")

    uid = decoded.get("uid")
    email = decoded.get("email")
    name = decoded.get("name") or decoded.get("email", "").split("@")[0]
    avatar_url = decoded.get("picture")

    if not uid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Firebase token missing uid")

    user, is_new = await get_or_create_user(
        db,
        firebase_uid=uid,
        email=email,
        phone=None,
        name=name,
        avatar_url=avatar_url,
    )
    return await _issue_token_response(user, is_new, db)


@router.post("/phone/send-otp", status_code=status.HTTP_200_OK)
async def send_otp(body: PhoneSendOTPRequest) -> dict[str, str]:
    return {"message": "OTP sent"}


@router.post("/phone/verify", response_model=AuthResponse)
async def phone_verify(
    body: PhoneVerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    try:
        decoded = verify_firebase_token(body.firebase_token)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Firebase token")

    uid = decoded.get("uid")
    phone = decoded.get("phone_number") or body.phone

    if not uid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Firebase token missing uid")

    name = phone.replace("+91", "") if phone else "Student"

    user, is_new = await get_or_create_user(
        db,
        firebase_uid=uid,
        email=None,
        phone=phone,
        name=name,
        avatar_url=None,
    )
    return await _issue_token_response(user, is_new, db)


@router.post("/refresh", response_model=TokenRefreshResponse)
async def refresh_token(user: User = Depends(get_current_user)) -> TokenRefreshResponse:
    token, jti = create_access_token(user.id, user.role)
    await store_token_jti(jti)
    return TokenRefreshResponse(access_token=token)


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    auth_header = request.headers.get("Authorization", "")
    try:
        token = auth_header.removeprefix("Bearer ")
        payload = decode_access_token(token)
        jti = payload.get("jti")
        if jti:
            await invalidate_token(jti)
    except ValueError:
        pass

    return {"message": "Logged out"}
