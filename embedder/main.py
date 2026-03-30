import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))

_model = None
_tokenizer = None


def load_model():
    global _model, _tokenizer
    if _model is not None and _tokenizer is not None:
        return _model, _tokenizer
    from mlx_embeddings import load
    logger.info(f"Loading MLX embedding model: {MODEL_NAME}")
    _model, _tokenizer = load(MODEL_NAME)
    logger.info("Model loaded successfully")
    return _model, _tokenizer


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()
    yield


app = FastAPI(title="MLX Embedding Service", lifespan=lifespan)


class EmbedRequest(BaseModel):
    texts: list[str]


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_NAME, "dim": EMBEDDING_DIM}


@app.post("/embed", response_model=EmbedResponse)
def embed(req: EmbedRequest):
    from mlx_embeddings import generate
    model, tokenizer = load_model()
    result = generate(model, tokenizer, req.texts)
    embeddings = result.pooler_output.tolist()
    return EmbedResponse(embeddings=embeddings)
