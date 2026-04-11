import json
import asyncio
import base64
import logging
from datetime import datetime, timezone, timedelta

TZ_VN = timezone(timedelta(hours=7))
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from api.redis_client import (
    save_audio_level,
    get_recent_audio,
    get_transcripts,
    save_transcript,
    get_redis,
)
from api.whisper_client import whisper_client

router = APIRouter(prefix="/api/realtime", tags=["realtime"])


class AudioData(BaseModel):
    device_id: str
    amplitude: float
    peak: float = 0.0


class TranscriptData(BaseModel):
    device_id: str
    text: str


class AudioResponse(BaseModel):
    time: str
    device_id: str
    amplitude: float
    peak: float


class TranscriptResponse(BaseModel):
    time: str
    device_id: str
    text: str


@router.get("/audio/{device_id}", response_model=list[AudioResponse])
def get_audio(device_id: str, limit: int = 100):
    return get_recent_audio(device_id, limit)


@router.get("/transcripts", response_model=list[TranscriptResponse])
def get_transcript_list(limit: int = 50):
    return get_transcripts(limit)


@router.post("/audio")
async def post_audio(data: AudioData):
    save_audio_level(data.device_id, data.amplitude, data.peak)
    await manager.publish_sse("audio", {
        "device_id": data.device_id,
        "amplitude": data.amplitude,
        "peak": data.peak,
        "time": datetime.now(TZ_VN).isoformat(),
    })
    return {"status": "ok"}


@router.post("/transcript")
async def post_transcript(data: TranscriptData):
    save_transcript(data.device_id, data.text)
    await manager.publish_sse("transcript", {
        "device_id": data.device_id,
        "text": data.text,
        "time": datetime.now(TZ_VN).isoformat(),
    })
    # Session RAG hook
    from api.services.session_service import (
        get_active_session_id, save_session_transcript, schedule_batch
    )
    import concurrent.futures as _cf
    _sid = get_active_session_id()
    if _sid:
        _cf.ThreadPoolExecutor(max_workers=1).submit(
            save_session_transcript, _sid, data.device_id, data.text
        )
        schedule_batch(_sid)
    return {"status": "ok"}


@router.post("/transcribe/ws")
async def transcribe_ws_audio(device_id: str = "esp32-001", data: bytes = None):
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Received audio for transcription: {len(data) if data else 0} bytes")
    return {"status": "received"}


@router.post("/transcribe")
async def transcribe_audio(device_id: str = "esp32-001", file: UploadFile = File(...)):
    audio_data = await file.read()
    text = whisper_client.transcribe(audio_data)
    if text:
        save_transcript(device_id, text)
        await manager.publish_sse("transcript", {
            "device_id": device_id,
            "text": text,
            "time": datetime.now(TZ_VN).isoformat(),
        })
        # Session RAG hook
        from api.services.session_service import (
            get_active_session_id, save_session_transcript, schedule_batch
        )
        import concurrent.futures as _cf
        _sid = get_active_session_id()
        if _sid:
            _cf.ThreadPoolExecutor(max_workers=1).submit(
                save_session_transcript, _sid, device_id, text
            )
            schedule_batch(_sid)
    return {"text": text}


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.sse_queues: list[asyncio.Queue] = []

    async def connect(self, websocket: WebSocket, device_id: str):
        await websocket.accept()
        self.active_connections[device_id] = websocket
        r = get_redis()
        r.sadd("connected_devices", device_id)

    def disconnect(self, device_id: str):
        if device_id in self.active_connections:
            del self.active_connections[device_id]
        r = get_redis()
        r.srem("connected_devices", device_id)

    async def send_audio(self, device_id: str, data: dict):
        if device_id in self.active_connections:
            await self.active_connections[device_id].send_json({
                "type": "audio",
                "data": data
            })

    async def broadcast_audio(self, data: dict):
        for ws in self.active_connections.values():
            await ws.send_json({
                "type": "audio",
                "data": data
            })

    def add_sse_queue(self):
        q = asyncio.Queue()
        self.sse_queues.append(q)
        return q

    def remove_sse_queue(self, q: asyncio.Queue):
        if q in self.sse_queues:
            self.sse_queues.remove(q)

    async def publish_sse(self, event: str, data: dict):
        dead = []
        for q in self.sse_queues:
            try:
                q.put_nowait({"event": event, "data": data})
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.remove_sse_queue(q)


manager = ConnectionManager()


@router.get("/stream")
async def sse_stream():
    q = manager.add_sse_queue()
    async def event_generator():
        try:
            ping_count = 0
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=25)
                    event = item["event"]
                    payload = json.dumps(item["data"])
                    yield f"event: {event}\ndata: {payload}\n\n"
                    ping_count = 0
                except asyncio.TimeoutError:
                    ping_count += 1
                    yield f"event: ping\ndata: {{\"count\": {ping_count}}}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            manager.remove_sse_queue(q)
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.websocket("/ws")
async def websocket_root(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket connected (root)")
    try:
        while True:
            msg = await websocket.receive()
            if msg["type"] == "text":
                data = msg["text"]
                try:
                    payload = json.loads(data)
                    device_id = payload.get("device_id", "esp32-001")
                    audio_type = payload.get("type", "audio")
                    if audio_type == "audio":
                        amplitude = payload.get("amplitude", 0)
                        peak = payload.get("peak", 0)
                        save_audio_level(device_id, amplitude, peak)
                        await manager.publish_sse("audio", {
                            "device_id": device_id,
                            "amplitude": amplitude,
                            "peak": peak,
                            "time": datetime.now(TZ_VN).isoformat(),
                        })
                except json.JSONDecodeError:
                    pass
            elif msg["type"] == "bytes":
                audio_data = msg["bytes"]
                logger.info(f"Received binary audio: {len(audio_data)} bytes")
                device_id = "esp32-001"
                text = whisper_client.transcribe(audio_data)
                if text:
                    save_transcript(device_id, text)
                    await manager.publish_sse("transcript", {
                        "device_id": device_id,
                        "text": text,
                        "time": datetime.now(TZ_VN).isoformat(),
                    })
    except Exception as e:
        logger.error(f"WS error: {e}")
    finally:
        logger.info("WebSocket disconnected (root)")


@router.websocket("/ws/{device_id}")
async def websocket_endpoint(websocket: WebSocket, device_id: str):
    await manager.connect(websocket, device_id)
    logger.info(f"WebSocket connected: {device_id}")
    try:
        while True:
            try:
                msg = await websocket.receive()
                if msg["type"] == "text":
                    data = msg["text"]
                    logger.info(f"WS received: {data[:80]}")
                    try:
                        payload = json.loads(data)
                        audio_type = payload.get("type", "audio")

                        if audio_type == "audio":
                            amplitude = payload.get("amplitude", 0)
                            peak = payload.get("peak", 0)
                            save_audio_level(device_id, amplitude, peak)
                            await manager.publish_sse("audio", {
                                "device_id": device_id,
                                "amplitude": amplitude,
                                "peak": peak,
                                "time": datetime.now(TZ_VN).isoformat(),
                            })

                        elif audio_type == "transcript":
                            text = payload.get("text", "")
                            if text:
                                save_transcript(device_id, text)
                                await manager.publish_sse("transcript", {
                                    "device_id": device_id,
                                    "text": text,
                                    "time": datetime.now(TZ_VN).isoformat(),
                                })
                                # Session RAG hook
                                from api.services.session_service import (
                                    get_active_session_id, save_session_transcript, schedule_batch
                                )
                                import concurrent.futures as _cf
                                _sid = get_active_session_id()
                                if _sid:
                                    _cf.ThreadPoolExecutor(max_workers=1).submit(
                                        save_session_transcript, _sid, device_id, text
                                    )
                                    schedule_batch(_sid)

                    except json.JSONDecodeError as e:
                        logger.error(f"JSON error: {e}")
                elif msg["type"] == "bytes":
                    audio_data = msg["bytes"]
                    logger.info(f"WS received binary audio: {len(audio_data)} bytes")
                    # Transcribe
                    text = whisper_client.transcribe(audio_data)
                    if text:
                        save_transcript(device_id, text)
                        await manager.publish_sse("transcript", {
                            "device_id": device_id,
                            "text": text,
                            "time": datetime.now(TZ_VN).isoformat(),
                        })
            except RuntimeError:
                break
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {device_id}")
        manager.disconnect(device_id)
