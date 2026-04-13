import logging
import os
import io
from contextlib import asynccontextmanager

import numpy as np
import soundfile as sf
from fastapi import FastAPI, Request
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_MODEL_DIR  = os.getenv(
    "ZIPFORMER_MODEL_DIR",
    os.path.join(os.path.dirname(__file__), "..", "models", "zipformer")
)
NUM_THREADS = int(os.getenv("NUM_THREADS", "4"))
SAMPLE_RATE = 16000
# chunk-16 = lowest latency; change to chunk-32 / chunk-64 for better accuracy
CHUNK       = os.getenv("ZIPFORMER_CHUNK", "16")

_recognizer = None


def _model_path(name: str) -> str:
    return os.path.join(_MODEL_DIR, name)


def load_model():
    global _recognizer
    import sherpa_onnx

    encoder = _model_path(f"encoder-epoch-31-avg-11-chunk-{CHUNK}-left-128.fp16.onnx")
    decoder = _model_path(f"decoder-epoch-31-avg-11-chunk-{CHUNK}-left-128.fp16.onnx")
    joiner  = _model_path(f"joiner-epoch-31-avg-11-chunk-{CHUNK}-left-128.fp16.onnx")
    tokens  = _model_path("tokens.txt")

    for f in (encoder, decoder, joiner, tokens):
        if not os.path.exists(f):
            raise FileNotFoundError(f"Model file not found: {f}")

    logger.info(f"Loading Zipformer RNNT streaming (chunk={CHUNK}) from {_MODEL_DIR}")

    _recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
        encoder         = encoder,
        decoder         = decoder,
        joiner          = joiner,
        tokens          = tokens,
        num_threads     = NUM_THREADS,
        sample_rate     = SAMPLE_RATE,
        feature_dim     = 80,
        decoding_method = "greedy_search",
        # BPE with ▁ space prefix — sherpa handles SentencePiece post-processing
        modeling_unit   = "bpe",
        bpe_vocab       = _model_path("bpe.model"),
        enable_endpoint_detection = False,
        debug           = False,
    )
    logger.info("Zipformer RNNT loaded OK")


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()
    yield


app = FastAPI(title="Zipformer ASR Service", lifespan=lifespan)


class TranscribeResponse(BaseModel):
    text: str


def transcribe(audio: np.ndarray) -> str:
    """Transcribe a complete audio array (float32, 16kHz mono)."""
    stream = _recognizer.create_stream()
    stream.accept_waveform(SAMPLE_RATE, audio)

    # Feed ~1.0s of silence to flush the last partial frame from the encoder
    tail_samples = int(1.0 * SAMPLE_RATE)
    stream.accept_waveform(SAMPLE_RATE, np.zeros(tail_samples, dtype=np.float32))

    while _recognizer.is_ready(stream):
        _recognizer.decode_stream(stream)

    result = _recognizer.get_result(stream)
    # Model outputs UPPERCASE — convert to title-case Vietnamese
    return result.strip().capitalize() if result.strip() else ""


@app.get("/health")
def health():
    return {
        "status"  : "ok" if _recognizer is not None else "loading",
        "model"   : f"hynt/Zipformer-30M-RNNT-Streaming-6000h (chunk={CHUNK})",
        "backend" : "sherpa-onnx",
        "threads" : NUM_THREADS,
    }


@app.post("/transcribe/wav")
async def transcribe_wav(request: Request):
    try:
        raw = await request.body()
        if not raw:
            return TranscribeResponse(text="")

        audio, sr = sf.read(io.BytesIO(raw))

        if sr != SAMPLE_RATE:
            import librosa
            audio = librosa.resample(audio, orig_sr=sr, target_sr=SAMPLE_RATE)

        if audio.ndim > 1:
            audio = audio.mean(axis=1)

        audio = audio.astype(np.float32)
        text = transcribe(audio)
        logger.info(f"Zipformer → {text!r}")
        return TranscribeResponse(text=text)

    except Exception as e:
        logger.error(f"Transcription error: {e}", exc_info=True)
        return TranscribeResponse(text="")
