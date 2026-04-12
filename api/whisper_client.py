import os
import re
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

WHISPER_SERVICE_URL = os.getenv("WHISPER_SERVICE_URL", "http://localhost:8002")

# Whisper commonly hallucinates these on silence/noise — exact match after normalising
_HALLUCINATIONS: set[str] = {
    "", ".", "..", "...", "…",
    "thank you", "thanks", "you", "bye", "goodbye", "hello",
    "thank you.", "thanks.", "you.", "bye.", "hello.",
    "thank you for watching", "please subscribe", "like and subscribe",
    "[music]", "[applause]", "[laughter]", "[silence]", "[noise]",
    "♪", "♫", "[ music ]",
    "subtitles by", "subtitles by the community",
}

# Patterns that indicate hallucination regardless of exact text
_HALLUCINATION_RE = re.compile(
    r"^[\s.…,!?♪♫\[\]()]+$"          # only punctuation/symbols
    r"|^\[.*\]$"                        # [anything]
    r"|\b(\w+)\b(?:\s+\1){2,}",        # same word repeated 3+ times
    re.IGNORECASE,
)


def is_garbage(text: str) -> bool:
    """Return True if text looks like a Whisper hallucination or noise artifact."""
    t = text.strip()
    if not t:
        return True
    # Too short to be real speech
    if len(t) < 3:
        return True
    # Known hallucination phrases
    if t.lower().rstrip(" .!?,") in _HALLUCINATIONS:
        return True
    # Pattern-based
    if _HALLUCINATION_RE.search(t):
        return True
    # Ratio of punctuation/spaces to total chars too high
    alpha = sum(c.isalpha() for c in t)
    if alpha < len(t) * 0.4:
        return True
    return False


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
            text = resp.json().get("text", "").strip()
            logger.info(f"Whisper raw: {text!r}")
            if is_garbage(text):
                logger.info(f"Dropped as garbage: {text!r}")
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
