import os
import json
from datetime import datetime, timezone, timedelta
from typing import Optional
import redis

TZ_VN = timezone(timedelta(hours=7))

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

_redis_client: Optional[redis.Redis] = None

AUDIO_KEY_PREFIX = "audio:"
TRANSCRIPT_KEY = "transcripts:latest"


def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


def save_audio_level(device_id: str, amplitude: float, peak: float = 0.0):
    r = get_redis()
    key = f"{AUDIO_KEY_PREFIX}{device_id}"
    data = {
        "time": datetime.now(TZ_VN).isoformat(),
        "device_id": device_id,
        "amplitude": amplitude,
        "peak": peak,
    }
    r.lpush(key, json.dumps(data))
    r.ltrim(key, 0, 199)
    r.expire(key, 60)


def get_recent_audio(device_id: str, limit: int = 100) -> list[dict]:
    r = get_redis()
    key = f"{AUDIO_KEY_PREFIX}{device_id}"
    items = r.lrange(key, 0, limit - 1)
    return [json.loads(item) for item in items]


def save_transcript(device_id: str, text: str) -> bool:
    """Save transcript to Redis. Returns False and skips if text is garbage."""
    from api.whisper_client import is_garbage
    if is_garbage(text):
        return False
    r = get_redis()
    data = {
        "time": datetime.now(TZ_VN).isoformat(),
        "device_id": device_id,
        "text": text,
    }
    r.lpush(TRANSCRIPT_KEY, json.dumps(data))
    r.ltrim(TRANSCRIPT_KEY, 0, 99)
    r.expire(TRANSCRIPT_KEY, 3600)
    return True


def get_transcripts(limit: int = 50) -> list[dict]:
    r = get_redis()
    items = r.lrange(TRANSCRIPT_KEY, 0, limit - 1)
    return [json.loads(item) for item in items]


def get_connected_devices() -> list[str]:
    r = get_redis()
    return list(r.smembers("connected_devices"))
