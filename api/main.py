"""FastAPI application entry point."""

import asyncio
import struct
import math
import time as _time
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


# ── WebRTC NS: single-pass level 3, inline (~0.3ms per packet) ──
from webrtc_noise_gain import AudioProcessor
_ns = AudioProcessor(0, 3)
_ns_buf = bytearray()
_FRAME = 320  # 10ms at 16kHz
_SILENCE = b"\x00" * _FRAME
_hold = 0


def _clean_pcm(raw: bytes) -> bytes:
    global _ns_buf, _hold
    _ns_buf.extend(raw)
    out = bytearray()
    while len(_ns_buf) >= _FRAME:
        frame = bytes(_ns_buf[:_FRAME])
        _ns_buf = _ns_buf[_FRAME:]
        r = _ns.Process10ms(frame)
        if r.is_speech:
            _hold = 15
        elif _hold > 0:
            _hold -= 1
        out.extend(r.audio if _hold > 0 else _SILENCE)
    return bytes(out)


def compute_audio_levels(raw_bytes: bytes) -> tuple[float, float]:
    if len(raw_bytes) < 2:
        return 0.0, 0.0
    n_samples = len(raw_bytes) // 2
    samples = struct.unpack(f"<{n_samples}h", raw_bytes[:n_samples * 2])
    peak = max(abs(s) for s in samples) / 32768.0
    rms = math.sqrt(sum(s * s for s in samples) / n_samples) / 32768.0
    return round(rms, 6), round(peak, 6)


IMAGES_DIR = Path("data/images")
IMAGES_DIR.mkdir(parents=True, exist_ok=True)


def _get_lan_ip() -> str:
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _start_mdns():
    import subprocess
    ip = _get_lan_ip()
    try:
        proc = subprocess.Popen(
            ["dns-sd", "-P", "process-docs", "_http._tcp", "local", "8000",
             "process-docs.local", ip],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        logger.info(f"mDNS: process-docs.local → {ip}:8000")
        return proc
    except Exception:
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    loop = asyncio.get_event_loop()
    mdns_proc = await loop.run_in_executor(None, _start_mdns)
    yield
    if mdns_proc:
        mdns_proc.terminate()


app = FastAPI(title="Knowledge Base API", lifespan=lifespan)

# Browser audio monitor clients
_audio_monitor_clients: set[WebSocket] = set()


async def _broadcast_pcm(data: bytes) -> None:
    dead = set()
    for ws in _audio_monitor_clients:
        try:
            await ws.send_bytes(data)
        except Exception:
            dead.add(ws)
    _audio_monitor_clients.difference_update(dead)


@app.websocket("/ws/audio-monitor")
async def audio_monitor_ws(websocket: WebSocket):
    await websocket.accept()
    _audio_monitor_clients.add(websocket)
    try:
        while True:
            await websocket.receive()
    except Exception:
        pass
    finally:
        _audio_monitor_clients.discard(websocket)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
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


async def _transcribe_bg(device_id: str, chunk: bytes):
    try:
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, whisper_client.transcribe, chunk)
        if text:
            save_transcript(device_id, text)
            await manager.publish_sse("transcript", {
                "device_id": device_id,
                "text": text,
                "time": datetime.now(TZ_VN).isoformat(),
            })
            logger.info(f"Transcript: {text}")
            from api.services.session_service import fire_session_rag_hook
            loop.run_in_executor(None, fire_session_rag_hook, device_id, text)
    except Exception as e:
        logger.error(f"Transcribe error: {e}")


@app.websocket("/ws")
async def websocket_root(websocket: WebSocket):
    await websocket.accept()
    logger.info("ESP32 connected")
    try:
        await websocket.send_text("ACK: connected")
    except Exception:
        return

    audio_buffer = bytearray()
    device_id = "esp32-001"
    amp_acc: list[float] = []
    peak_acc: list[float] = []
    last_sse = _time.monotonic()

    try:
        while True:
            msg = await websocket.receive()

            if msg.get("type") == "websocket.disconnect":
                break

            if "bytes" not in msg:
                continue

            audio_data = msg["bytes"]

            # 1) Amplitude (cheap math)
            amplitude, peak = compute_audio_levels(audio_data)
            amp_acc.append(amplitude)
            peak_acc.append(peak)

            # 2) SSE every ~1s for chart
            now = _time.monotonic()
            if now - last_sse >= 1.0 and amp_acc:
                avg_amp = sum(amp_acc) / len(amp_acc)
                avg_peak = max(peak_acc)
                amp_acc.clear()
                peak_acc.clear()
                last_sse = now
                save_audio_level(device_id, avg_amp, avg_peak)
                await manager.publish_sse("audio", {
                    "device_id": device_id,
                    "amplitude": round(avg_amp, 6),
                    "peak": round(avg_peak, 6),
                    "time": datetime.now(TZ_VN).isoformat(),
                })

            # 3) Denoise + forward to browser audio
            clean = _clean_pcm(audio_data)
            if _audio_monitor_clients and clean:
                asyncio.create_task(_broadcast_pcm(clean))

            # 4) Whisper every ~2s (uses raw audio — whisper handles noise itself)
            audio_buffer.extend(audio_data)
            if len(audio_buffer) >= 64000:
                chunk = bytes(audio_buffer)
                audio_buffer.clear()
                asyncio.create_task(_transcribe_bg(device_id, chunk))

    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception as e:
        logger.info(f"ESP32 WS closed: {type(e).__name__}")
    finally:
        logger.info("ESP32 disconnected")


@app.get("/api/health")
def health():
    return {"status": "ok"}
