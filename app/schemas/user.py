from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class FirebaseGoogleRequest(BaseModel):
    firebase_token: str


class PhoneSendOTPRequest(BaseModel):
    phone: str

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        if not v.startswith("+") or len(v) < 10:
            raise ValueError("Phone must be in E.164 format, e.g. +919876543210")
        return v


class PhoneVerifyRequest(BaseModel):
    phone: str
    firebase_token: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    phone: str | None
    email: str | None
    avatar_url: str | None
    role: str
    current_class: int | None
    medium: str
    free_trial_expires_at: datetime | None = None
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    is_new_user: bool
    user: UserResponse


class UserUpdateRequest(BaseModel):
    name: str | None = None
    current_class: int | None = None
    medium: str | None = None

    @field_validator("current_class")
    @classmethod
    def validate_class(cls, v: int | None) -> int | None:
        if v is not None and v not in range(7, 11):
            raise ValueError("current_class must be between 7 and 10")
        return v

    @field_validator("medium")
    @classmethod
    def validate_medium(cls, v: str | None) -> str | None:
        if v is not None and v not in ("malayalam", "english"):
            raise ValueError("medium must be 'malayalam' or 'english'")
        return v


class UserStatsResponse(BaseModel):
    videos_completed: int
    tests_taken: int
    avg_test_score: float
    streak_days: int
    subjects_active: list[str]


class FCMTokenRequest(BaseModel):
    token: str
    platform: str

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        if v not in ("android", "ios", "web"):
            raise ValueError("platform must be 'android', 'ios', or 'web'")
        return v


class TokenRefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
