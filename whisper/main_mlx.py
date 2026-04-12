import logging
import os
import io
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, Request
from pydantic import BaseModel
import soundfile as sf

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_NAME = os.getenv("WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")

_model_loaded = False


def load_model():
    global _model_loaded
    if _model_loaded:
        return
    try:
        import mlx_whisper
        logger.info(f"Loading MLX whisper model: {MODEL_NAME}")
        mlx_whisper.transcribe(
            np.zeros(16000, dtype=np.float32),
            path_or_hf_repo=MODEL_NAME,
            language="en",
        )
        _model_loaded = True
        logger.info("MLX whisper model loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load whisper model: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()
    yield


app = FastAPI(title="Whisper Service (MLX)", lifespan=lifespan)


class TranscribeResponse(BaseModel):
    text: str


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "backend": "mlx",
    }


def is_silent(audio: np.ndarray) -> bool:
    rms = float(np.sqrt(np.mean(audio ** 2)))
    return rms < 0.005


def transcribe_audio(audio: np.ndarray, sample_rate: int) -> str:
    if not _model_loaded:
        return "Model not loaded"

    try:
        if is_silent(audio):
            return ""

        import mlx_whisper
        result = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=MODEL_NAME,
            language="en",
            task="transcribe",
            no_speech_threshold=0.6,
            hallucination_silence_threshold=2.0,
            condition_on_previous_text=False,
        )
        return result.get("text", "").strip()
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        return ""


@app.post("/transcribe/wav")
async def transcribe_wav(request: Request):
    try:
        file = await request.body()
        if not file:
            return TranscribeResponse(text="No audio file provided")

        audio_buffer = io.BytesIO(file)
        audio, sr = sf.read(audio_buffer)

        if sr != 16000:
            import librosa
            audio = librosa.resample(audio, orig_sr=sr, target_sr=16000)

        if audio.ndim > 1:
            audio = audio.mean(axis=1)

        audio = audio.astype(np.float32)
        text = transcribe_audio(audio, 16000)
        return TranscribeResponse(text=text)
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        return TranscribeResponse(text="")
