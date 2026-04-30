
import redis.asyncio as aioredis
from fastapi import HTTPException, Request, status
from slowapi import Limiter

from app.config import settings


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=get_client_ip, storage_uri=settings.REDIS_URL)

_rl_redis: aioredis.Redis | None = None


def _get_rl_redis() -> aioredis.Redis:
    global _rl_redis
    if _rl_redis is None:
        _rl_redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _rl_redis


async def check_identifier_rate_limit(key: str, max_requests: int, window_seconds: int) -> None:
    """Increment a per-identifier counter and raise 429 when the limit is exceeded."""
    r = _get_rl_redis()
    redis_key = f"rl:{key}"
    count = await r.incr(redis_key)
    if count == 1:
        await r.expire(redis_key, window_seconds)
    if count > max_requests:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please try again later.",
        )
