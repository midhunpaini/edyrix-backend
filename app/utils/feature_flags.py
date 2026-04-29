import json
from typing import Any

from redis.asyncio import Redis

_ALLOWED_FLAGS = {
    "free_trial_enabled",
    "trial_duration_days",
    "whatsapp_share_enabled",
    "maintenance_mode",
}

_DEFAULTS: dict[str, Any] = {
    "free_trial_enabled": True,
    "trial_duration_days": 7,
    "whatsapp_share_enabled": True,
    "maintenance_mode": False,
}


async def get_flag(redis: Redis, name: str, default: Any = None) -> Any:
    val = await redis.get(f"flag:{name}")
    if val is None:
        return _DEFAULTS.get(name, default)
    return json.loads(val)


async def set_flag(redis: Redis, name: str, value: Any) -> None:
    await redis.set(f"flag:{name}", json.dumps(value))


async def get_all_flags(redis: Redis) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in _ALLOWED_FLAGS:
        result[name] = await get_flag(redis, name)
    return result


def is_allowed_flag(name: str) -> bool:
    return name in _ALLOWED_FLAGS
