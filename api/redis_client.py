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


# ── Device registry (live, TTL-based heartbeat) ───────────────────
DEVICE_TTL = 30          # seconds; refreshed on hello + each heartbeat
ONLINE_SET = "online_devices"


def register_device(device_id: str, name: str = "", ip: str = "") -> None:
    """Mark a device online with metadata; (re)set its TTL."""
    r = get_redis()
    now = datetime.now(TZ_VN).isoformat()
    key = f"device:{device_id}"
    r.hset(key, mapping={
        "device_id": device_id,
        "name": name or device_id,
        "ip": ip,
        "connected_at": now,
        "last_seen": now,
    })
    r.expire(key, DEVICE_TTL)
    r.sadd(ONLINE_SET, device_id)


def touch_device(device_id: str) -> None:
    """Heartbeat: refresh last_seen + TTL if the device is still registered."""
    r = get_redis()
    key = f"device:{device_id}"
    if r.exists(key):
        r.hset(key, "last_seen", datetime.now(TZ_VN).isoformat())
        r.expire(key, DEVICE_TTL)


def unregister_device(device_id: str) -> None:
    """Remove a device from the online registry (on disconnect)."""
    r = get_redis()
    r.delete(f"device:{device_id}")
    r.srem(ONLINE_SET, device_id)


def get_online_devices() -> list[dict]:
    """Return metadata for devices whose TTL hash is still alive; prune the rest."""
    r = get_redis()
    out = []
    for device_id in r.smembers(ONLINE_SET):
        meta = r.hgetall(f"device:{device_id}")
        if meta:
            out.append(meta)
        else:
            r.srem(ONLINE_SET, device_id)   # TTL expired → prune stale id
    return sorted(out, key=lambda d: d.get("connected_at", ""))
