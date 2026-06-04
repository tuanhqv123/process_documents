from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from api.redis_client import get_online_devices

router = APIRouter(prefix="/api", tags=["devices"])


class DeviceOut(BaseModel):
    device_id: str
    name: str
    connected_at: Optional[str] = None
    last_seen: Optional[str] = None
    ip: Optional[str] = None


@router.get("/devices", response_model=list[DeviceOut])
def list_devices():
    """List ESP32 devices currently online (live Redis registry)."""
    return get_online_devices()
