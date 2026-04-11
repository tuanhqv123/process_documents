"""FastAPI application entry point."""

import asyncio
import struct
import math
from datetime import datetime, timezone, timedelta

TZ_VN = timezone(timedelta(hours=7))
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from api import db as database
from api.routes.documents import router as docs_router, chunks_router, images_router
from api.routes.workspaces import router as ws_router
from api.routes.search import router as search_router
from api.routes.realtime import router as realtime_router, manager, save_audio_level, save_transcript, whisper_client
from api.routes.extract import router as extract_router
from api.routes.api_keys import router as api_keys_router
from api.routes.sessions import router as sessions_router

import json
import logging

logger = logging.getLogger(__name__)


def compute_audio_levels(raw_bytes: bytes) -> tuple[float, float]:
    """Extract amplitude (RMS) and peak from raw 16-bit PCM audio bytes."""
    if len(raw_bytes) < 2:
        return 0.0, 0.0
    n_samples = len(raw_bytes) // 2
    samples = struct.unpack(f"<{n_samples}h", raw_bytes[:n_samples * 2])
    peak = max(abs(s) for s in samples) / 32768.0
    rms = math.sqrt(sum(s * s for s in samples) / n_samples) / 32768.0
    return round(rms, 6), round(peak, 6)

IMAGES_DIR = Path("data/images")

IMAGES_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    yield


app = FastAPI(title="Knowledge Base API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static/images", StaticFiles(directory=str(IMAGES_DIR), html=False), name="images")

app.include_router(docs_router)
app.include_router(chunks_router)
app.include_router(images_router)
app.include_router(ws_router)
app.include_router(search_router)
app.include_router(realtime_router)
app.include_router(extract_router)
app.include_router(api_keys_router)
app.include_router(sessions_router)


@app.websocket("/ws")
async def websocket_root(websocket: WebSocket):
    await websocket.accept()
    print("="*50)
    print("ESP32 WebSocket CONNECTED - STARTING LOOP")
    print("="*50)
    logger.info("=== ESP32 WebSocket connected ===")
    await websocket.send_text("ACK: connected")
    audio_buffer = bytearray()
    try:
        while True:
            msg = await websocket.receive()
            msg_type = msg.get("type", "")
            
            if "bytes" in msg:
                audio_data = msg["bytes"]
                device_id = "esp32-001"
                logger.info(f"WS binary: {len(audio_data)} bytes")

                # Always compute and publish audio levels from raw PCM
                amplitude, peak = compute_audio_levels(audio_data)
                save_audio_level(device_id, amplitude, peak)
                await manager.publish_sse("audio", {
                    "device_id": device_id,
                    "amplitude": amplitude,
                    "peak": peak,
                    "time": datetime.now(TZ_VN).isoformat(),
                })

                # Accumulate audio for whisper transcription
                audio_buffer.extend(audio_data)
                # Transcribe every ~2 seconds of audio (16kHz, 16-bit mono = 32000 bytes/sec)
                if len(audio_buffer) >= 64000:
                    chunk = bytes(audio_buffer)
                    audio_buffer.clear()
                    try:
                        text = whisper_client.transcribe(chunk)
                        if text:
                            save_transcript(device_id, text)
                            await manager.publish_sse("transcript", {
                                "device_id": device_id,
                                "text": text,
                                "time": datetime.now(TZ_VN).isoformat(),
                            })
                            logger.info(f"Transcript: {text}")
                            # Session RAG hook
                            from api.services.session_service import fire_session_rag_hook
                            import asyncio as _asyncio
                            _asyncio.get_event_loop().run_in_executor(
                                None, fire_session_rag_hook, device_id, text
                            )
                    except Exception as e:
                        logger.error(f"Transcribe error: {e}")

            elif msg_type == "text" or ("text" in msg and msg.get("text")):
                data = msg.get("text", "")
                try:
                    payload = json.loads(data)
                    device_id = payload.get("device_id", "esp32-001")
                    amplitude = payload.get("amplitude", 0)
                    peak = payload.get("peak", 0)
                    save_audio_level(device_id, amplitude, peak)
                    await manager.publish_sse("audio", {
                        "device_id": device_id,
                        "amplitude": amplitude,
                        "peak": peak,
                        "time": datetime.now(TZ_VN).isoformat(),
                    })
                except:
                    pass
    except WebSocketDisconnect:
        logger.info("ESP32 WebSocket disconnected")
    except Exception as e:
        logger.error(f"WS error: {e}")


@app.get("/api/health")
def health():
    return {"status": "ok"}
