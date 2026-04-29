import asyncio
import functools

import boto3
from botocore.config import Config

from app.config import settings


def _s3_client() -> boto3.client:
    """Return a configured boto3 S3-compatible client for Cloudflare R2."""
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


async def generate_presigned_url(r2_key: str, expires_in: int = 3600) -> str:
    """Generate a time-limited presigned GET URL for an R2 object."""
    client = _s3_client()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        functools.partial(
            client.generate_presigned_url,
            "get_object",
            Params={"Bucket": settings.R2_BUCKET_NAME, "Key": r2_key},
            ExpiresIn=expires_in,
        ),
    )


async def upload_bytes(
    data: bytes,
    r2_key: str,
    content_type: str = "application/octet-stream",
) -> None:
    """Upload raw bytes to R2 under the given key."""
    client = _s3_client()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        functools.partial(
            client.put_object,
            Bucket=settings.R2_BUCKET_NAME,
            Key=r2_key,
            Body=data,
            ContentType=content_type,
        ),
    )


async def delete_object(r2_key: str) -> None:
    """Delete an object from R2, swallowing errors so the DB delete still commits."""
    client = _s3_client()
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(
            None,
            functools.partial(client.delete_object, Bucket=settings.R2_BUCKET_NAME, Key=r2_key),
        )
    except Exception:
        pass


async def download_bytes(r2_key: str) -> bytes:
    """Download and return the raw bytes for an R2 object."""
    client = _s3_client()
    loop = asyncio.get_running_loop()
    response = await loop.run_in_executor(
        None,
        functools.partial(
            client.get_object,
            Bucket=settings.R2_BUCKET_NAME,
            Key=r2_key,
        ),
    )
    return response["Body"].read()
