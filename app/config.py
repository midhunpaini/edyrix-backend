from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # App
    APP_NAME: str = "Edyrix"
    APP_ENV: Literal["development", "production"] = "development"
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    FRONTEND_URL: str = "http://localhost:5173"
    ADMIN_URL: str = "http://localhost:5174"

    # Database
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_ASYNC_PREFIX: str = "postgresql+asyncpg://"
    POSTGRES_SYNC_PREFIX: str = "postgresql://"

    @property
    def DATABASE_URL(self) -> str:
        return f"{self.POSTGRES_ASYNC_PREFIX}{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    @property
    def DATABASE_SYNC_URL(self) -> str:
        return f"{self.POSTGRES_SYNC_PREFIX}{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    # Redis
    REDIS_URL: str

    # Firebase
    FIREBASE_PROJECT_ID: str
    FIREBASE_PRIVATE_KEY: str
    FIREBASE_CLIENT_EMAIL: str

    # Razorpay
    RAZORPAY_KEY_ID: str
    RAZORPAY_KEY_SECRET: str
    RAZORPAY_WEBHOOK_SECRET: str

    # Cloudflare R2
    R2_ACCOUNT_ID: str
    R2_ACCESS_KEY_ID: str
    R2_SECRET_ACCESS_KEY: str
    R2_BUCKET_NAME: str = "edyrix-assets"
    R2_PUBLIC_URL: str

    # Resend
    RESEND_API_KEY: str
    FROM_EMAIL: str = "noreply@edyrix.in"

    @field_validator("FIREBASE_PRIVATE_KEY")
    @classmethod
    def fix_firebase_private_key(cls, v: str) -> str:
        return v.replace("\\n", "\n")

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


settings = Settings()
