import logging
import os
import base64
import io
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, Request
from pydantic import BaseModel
import soundfile as sf

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_NAME = os.getenv("WHISPER_MODEL", "openai/whisper-base")
VAD_THRESHOLD = float(os.getenv("VAD_THRESHOLD", "0.5"))

_pipe = None
_vad_model = None
_vad_utils = None


def load_model():
    global _pipe, _vad_model, _vad_utils
    if _pipe is not None:
        return

    try:
        import torch
        from transformers import pipeline, AutoModelForSpeechSeq2Seq, AutoProcessor
        from transformers.utils import is_flash_attn_2_available

        device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        torch_dtype = torch.float16 if device != "cpu" else torch.float32

        attn_impl = "flash_attention_2" if is_flash_attn_2_available() else "sdpa"

        logger.info(f"Loading whisper model: {MODEL_NAME} on {device} with {attn_impl}")

        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            MODEL_NAME,
            torch_dtype=torch_dtype,
            low_cpu_mem_usage=True,
            attn_implementation=attn_impl,
        )
        model.to(device)

        processor = AutoProcessor.from_pretrained(MODEL_NAME)

        _pipe = pipeline(
            "automatic-speech-recognition",
            model=model,
            tokenizer=processor.tokenizer,
            feature_extractor=processor.feature_extractor,
            max_new_tokens=256,
            torch_dtype=torch_dtype,
            device=device,
        )

        logger.info("Whisper model loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load whisper model: {e}")

    # Load Silero VAD
    try:
        import torch
        logger.info("Loading Silero VAD model...")
        _vad_model, _vad_utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            verbose=False,
            trust_repo=True,
        )
        _vad_model.eval()
        logger.info("Silero VAD loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load Silero VAD: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()
    yield


app = FastAPI(title="Whisper Service", lifespan=lifespan)


class TranscribeRequest(BaseModel):
    audio_data: str
    sample_rate: int = 16000


class TranscribeResponse(BaseModel):
    text: str


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "backend": "transformers",
        "vad": _vad_model is not None,
        "denoise": True,
    }


def denoise_rnnoise(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """Denoise audio using noisereduce (spectral noise gating)."""
    try:
        import noisereduce as nr
        denoised = nr.reduce_noise(y=audio, sr=sample_rate, stationary=False)
        return denoised.astype(np.float32)
    except Exception as e:
        logger.warning(f"Denoising failed, using raw audio: {e}")
        return audio


def has_speech_vad(audio: np.ndarray, sample_rate: int) -> bool:
    """Returns True if Silero VAD detects speech in the audio."""
    if _vad_model is None:
        # Fallback: simple RMS threshold
        rms = float(np.sqrt(np.mean(audio ** 2)))
        return rms >= 0.01

    try:
        import torch

        # Silero VAD requires 16kHz mono float32
        if sample_rate != 16000:
            import librosa
            audio_16k = librosa.resample(audio, orig_sr=sample_rate, target_sr=16000)
        else:
            audio_16k = audio.copy()

        audio_tensor = torch.from_numpy(audio_16k).float()

        get_speech_timestamps = _vad_utils[0]
        timestamps = get_speech_timestamps(
            audio_tensor,
            _vad_model,
            threshold=VAD_THRESHOLD,
            sampling_rate=16000,
            min_speech_duration_ms=100,
            min_silence_duration_ms=100,
        )
        return len(timestamps) > 0
    except Exception as e:
        logger.warning(f"Silero VAD failed, falling back to RMS: {e}")
        rms = float(np.sqrt(np.mean(audio ** 2)))
        return rms >= 0.01


def transcribe_audio(audio: np.ndarray, sample_rate: int) -> str:
    global _pipe

    if _pipe is None:
        return "Model not loaded"

    try:
        # Step 1: Denoise with RNNoise
        audio = denoise_rnnoise(audio, sample_rate)

        # Step 2: VAD — skip silent/non-speech frames
        if not has_speech_vad(audio, sample_rate):
            logger.debug("VAD: no speech detected, skipping transcription")
            return ""

        # Step 3: Transcribe with Whisper
        chunk_length = 30 if len(audio) / sample_rate > 30 else None
        result = _pipe(
            audio,
            chunk_length_s=chunk_length,
            return_timestamps=False,
            generate_kwargs={"language": "en", "task": "transcribe"},
        )
        return result.get("text", "").strip()
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        return ""


@app.post("/transcribe", response_model=TranscribeResponse)
def transcribe_req(req: TranscribeRequest):
    try:
        audio_bytes = base64.b64decode(req.audio_data)
        audio_buffer = io.BytesIO(audio_bytes)
        audio, sr = sf.read(audio_buffer)

        if sr != req.sample_rate:
            import librosa
            audio = librosa.resample(audio, orig_sr=sr, target_sr=req.sample_rate)

        if audio.ndim > 1:
            audio = audio.mean(axis=1)

        audio = audio.astype(np.float32)
        text = transcribe_audio(audio, req.sample_rate)
        return TranscribeResponse(text=text)
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        return TranscribeResponse(text="")


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
