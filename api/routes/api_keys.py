"""API key management routes (OCR/LLM model configuration)."""

import time
import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from api.db import get_session, ApiKey
from api.models import ApiKeyCreate, ApiKeyUpdate, ApiKeyOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


def _get_db():
    db = get_session()
    try:
        yield db
    finally:
        db.close()


def _key_out(r: ApiKey) -> ApiKeyOut:
    return ApiKeyOut(
        id=r.id,
        label=r.label,
        type=r.type,
        model_name=r.model_name or "",
        is_active=r.is_active,
        created_at=r.created_at.isoformat() if r.created_at else "",
    )


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[ApiKeyOut])
def list_keys(db: Session = Depends(_get_db)):
    keys = db.query(ApiKey).order_by(ApiKey.type, ApiKey.created_at.desc()).all()
    return [_key_out(k) for k in keys]


@router.post("/", response_model=ApiKeyOut)
def create_key(body: ApiKeyCreate, db: Session = Depends(_get_db)):
    if body.type not in ("ocr", "llm"):
        raise HTTPException(400, "type must be 'ocr' or 'llm'")
    key = ApiKey(
        label=body.label,
        type=body.type,
        base_url=body.base_url,
        api_key=body.api_key,
        model_name=body.model_name,
        is_active=False,
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    return _key_out(key)


@router.put("/{key_id}", response_model=ApiKeyOut)
def update_key(key_id: int, body: ApiKeyUpdate, db: Session = Depends(_get_db)):
    key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not key:
        raise HTTPException(404, "Key not found")
    if body.label is not None:
        key.label = body.label
    if body.base_url is not None:
        key.base_url = body.base_url
    if body.api_key is not None:
        key.api_key = body.api_key
    if body.model_name is not None:
        key.model_name = body.model_name
    db.commit()
    db.refresh(key)
    return _key_out(key)


@router.delete("/{key_id}")
def delete_key(key_id: int, db: Session = Depends(_get_db)):
    key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not key:
        raise HTTPException(404, "Key not found")
    db.delete(key)
    db.commit()
    return {"ok": True}


# ── Activate ──────────────────────────────────────────────────────────────────

@router.post("/{key_id}/activate")
def activate_key(key_id: int, db: Session = Depends(_get_db)):
    """Set this key as the active one for its type; deactivate all others of same type."""
    key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not key:
        raise HTTPException(404, "Key not found")
    # Deactivate all keys of same type
    db.query(ApiKey).filter(ApiKey.type == key.type).update({"is_active": False})
    key.is_active = True
    db.commit()
    return {"ok": True}


# ── Test connection ────────────────────────────────────────────────────────────

class TestConnectionRequest(BaseModel):
    base_url: str
    api_key: Optional[str] = "0"
    model_name: Optional[str] = None


def _probe_openai_endpoint(base_url: str, api_key: str = "0") -> dict:
    """Probe an OpenAI-compatible endpoint: list models, measure latency."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key or "0", base_url=base_url.rstrip("/"))
    t0 = time.monotonic()
    try:
        models_resp = client.models.list()
        latency_ms = round((time.monotonic() - t0) * 1000)
        model_ids = [m.id for m in models_resp.data]
        return {"ok": True, "latency_ms": latency_ms, "models": model_ids, "error": None}
    except Exception as e:
        latency_ms = round((time.monotonic() - t0) * 1000)
        return {"ok": False, "latency_ms": latency_ms, "models": [], "error": str(e)}


@router.post("/test-connection")
def test_connection(body: TestConnectionRequest):
    """Test an OpenAI-compatible endpoint by URL."""
    if not body.base_url:
        raise HTTPException(400, "base_url is required")
    return _probe_openai_endpoint(body.base_url, body.api_key or "0")


@router.post("/{key_id}/test")
def test_key(key_id: int, db: Session = Depends(_get_db)):
    """Test the connection for a saved key."""
    key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not key:
        raise HTTPException(404, "Key not found")
    if not key.base_url:
        return {"ok": False, "latency_ms": 0, "models": [], "error": "No base_url configured"}
    return _probe_openai_endpoint(key.base_url, key.api_key or "0")
