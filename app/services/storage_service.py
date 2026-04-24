import boto3
from botocore.config import Config

from app.config import settings


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def generate_presigned_url(r2_key: str, expires_in: int = 3600) -> str:
    return _s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.R2_BUCKET_NAME, "Key": r2_key},
        ExpiresIn=expires_in,
    )


def upload_bytes(data: bytes, r2_key: str, content_type: str = "application/octet-stream") -> None:
    _s3_client().put_object(
        Bucket=settings.R2_BUCKET_NAME,
        Key=r2_key,
        Body=data,
        ContentType=content_type,
    )


def download_bytes(r2_key: str) -> bytes:
    response = _s3_client().get_object(Bucket=settings.R2_BUCKET_NAME, Key=r2_key)
    return response["Body"].read()
