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


# ── WebRTC noise suppression ──────────────────────────────────
from webrtc_noise_gain import AudioProcessor

_NS_FRAME = 320  # 10ms @ 16kHz (320 bytes, int16)


class AudioPipeline:
    """Per-connection WebRTC noise suppression."""

    def __init__(self):
        self._ns  = AudioProcessor(10, 3)
        self._buf = bytearray()

    def process(self, raw: bytes) -> bytes:
        """Returns denoised PCM bytes (same length as input, approximately)."""
        self._buf.extend(raw)
        out = bytearray()
        while len(self._buf) >= _NS_FRAME:
            frame = bytes(self._buf[:_NS_FRAME])
            self._buf = self._buf[_NS_FRAME:]
            out.extend(self._ns.Process10ms(frame).audio)
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
    """Return the first 192.168.x.x or 10.x.x.x LAN IP, skipping VPN (172.16-31.x)."""
    import netifaces
    for iface in netifaces.interfaces():
        for addr in netifaces.ifaddresses(iface).get(netifaces.AF_INET, []):
            ip = addr.get("addr", "")
            if ip.startswith("192.168.") or ip.startswith("10."):
                return ip
    return "127.0.0.1"


def _start_mdns():
    """Register process-docs.local via zeroconf (stable, no subprocess)."""
    import socket
    from zeroconf import ServiceInfo, Zeroconf

    ip  = _get_lan_ip()
    zc  = Zeroconf()
    info = ServiceInfo(
        "_http._tcp.local.",
        "process-docs._http._tcp.local.",
        addresses=[socket.inet_aton(ip)],
        port=8000,
        properties={b"path": b"/ws"},
        server="process-docs.local.",
    )
    zc.register_service(info)
    logger.info(f"mDNS: process-docs.local → {ip}:8000  (zeroconf)")
    return zc


def _stop_mdns(zc):
    try:
        zc.unregister_all_services()
        zc.close()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    loop = asyncio.get_event_loop()
    zc = await loop.run_in_executor(None, _start_mdns)
    yield
    await loop.run_in_executor(None, _stop_mdns, zc)


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

    pipeline = AudioPipeline()
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

            # 1) WebRTC denoise
            denoised = pipeline.process(audio_data)

            # 2) Amplitude → SSE chart every 500ms
            amplitude, peak = compute_audio_levels(audio_data)
            amp_acc.append(amplitude)
            peak_acc.append(peak)
            now = _time.monotonic()
            if now - last_sse >= 0.5 and amp_acc:
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

            # 3) Forward denoised audio to browser monitor
            if _audio_monitor_clients and denoised:
                asyncio.create_task(_broadcast_pcm(denoised))

            # 4) Buffer denoised audio, transcribe every 1.5s
            audio_buffer.extend(denoised)
            if len(audio_buffer) >= 48000:
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
