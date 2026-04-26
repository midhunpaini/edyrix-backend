from urllib.parse import urlparse

from arq import create_pool
from arq.connections import RedisSettings

from app.config import settings


def _redis_settings() -> RedisSettings:
    url = urlparse(settings.REDIS_URL)
    return RedisSettings(
        host=url.hostname or "localhost",
        port=url.port or 6379,
        database=int(url.path.lstrip("/") or 0),
        password=url.password,
    )


_pool = None


async def get_queue():
    global _pool
    if _pool is None:
        _pool = await create_pool(_redis_settings())
    return _pool


async def enqueue(func_name: str, **kwargs) -> None:
    pool = await get_queue()
    await pool.enqueue_job(func_name, **kwargs)
