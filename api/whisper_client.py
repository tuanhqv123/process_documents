import os
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

WHISPER_SERVICE_URL = os.getenv("WHISPER_SERVICE_URL", "http://localhost:8002")


class WhisperClient:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or WHISPER_SERVICE_URL

    def transcribe(self, audio_data: bytes) -> str:
        try:
            import numpy as np
            import io
            import wave
            audio_int16 = np.frombuffer(audio_data, dtype=np.int16)

            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(audio_int16.tobytes())
            wav_data = wav_buffer.getvalue()
            
            resp = httpx.post(
                f"{self.base_url}/transcribe/wav",
                content=wav_data,
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data.get("text", "").strip()
            if not text or len(text) < 2:
                return ""
            if text.count(".") > len(text) // 2:
                return ""
            return text
        except Exception as e:
            logger.error(f"Whisper transcription error: {e}")
            return ""

    def is_healthy(self) -> bool:
        try:
            resp = httpx.get(f"{self.base_url}/health", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False


whisper_client = WhisperClient()
