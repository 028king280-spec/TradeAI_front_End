import json
import time
from typing import Optional, Any
from app.core.config import settings
from app.core.logging import logger

_in_memory_cache = {}
_redis_client = None


def get_redis_client():
    global _redis_client
    if _redis_client is None and settings.REDIS_URL:
        try:
            import redis
            _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
            _redis_client.ping()
        except Exception as e:
            logger.info(f"Redis not reachable at {settings.REDIS_URL}. Using high-performance in-memory cache: {e}")
            _redis_client = False
    return _redis_client if _redis_client else None


class CacheService:
    """
    Unified caching abstraction:
    Uses Redis when connected, automatically falling back to an in-memory TTL cache.
    """

    @classmethod
    async def get(cls, key: str) -> Optional[Any]:
        r = get_redis_client()
        if r:
            try:
                val = r.get(key)
                return json.loads(val) if val else None
            except Exception as e:
                logger.warning(f"Redis get error on {key}: {e}")

        # In-memory fallback
        item = _in_memory_cache.get(key)
        if item:
            expires_at, val = item
            if time.time() < expires_at:
                return val
            else:
                del _in_memory_cache[key]
        return None

    @classmethod
    async def set(cls, key: str, value: Any, ttl_seconds: int = 60):
        r = get_redis_client()
        if r:
            try:
                r.setex(key, ttl_seconds, json.dumps(value, default=str))
                return
            except Exception as e:
                logger.warning(f"Redis set error on {key}: {e}")

        # In-memory fallback
        _in_memory_cache[key] = (time.time() + ttl_seconds, value)

    @classmethod
    async def delete(cls, key: str):
        r = get_redis_client()
        if r:
            try:
                r.delete(key)
            except Exception:
                pass
        _in_memory_cache.pop(key, None)
