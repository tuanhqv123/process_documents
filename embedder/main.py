import logging
import os
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "dangvantuan/vietnamese-embedding")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))
# PhoBERT-based models max out at 256 tokens (max_position_embeddings=258).
# Cap here so long inputs are truncated instead of crashing with an index error.
MAX_SEQ_LEN = int(os.getenv("EMBEDDING_MAX_SEQ_LEN", "256"))

_model: SentenceTransformer | None = None


def load_model():
    global _model
    if _model is not None:
        return _model
    logger.info(f"Loading model: {MODEL_NAME}")
    _model = SentenceTransformer(MODEL_NAME)
    _model.max_seq_length = MAX_SEQ_LEN   # truncate long text → avoid PhoBERT position overflow
    logger.info(f"Model loaded successfully (max_seq_length={MAX_SEQ_LEN})")
    return _model


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, load_model)
    yield


app = FastAPI(title="Embedding Service", lifespan=lifespan)


class EmbedRequest(BaseModel):
    texts: list[str]


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_NAME, "dim": EMBEDDING_DIM}


@app.post("/embed", response_model=EmbedResponse)
def embed(req: EmbedRequest):
    model = load_model()
    vecs = model.encode(req.texts, normalize_embeddings=True)
    return EmbedResponse(embeddings=vecs.tolist())
