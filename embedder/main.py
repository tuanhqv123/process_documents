import logging
import os
from contextlib import asynccontextmanager

import mlx.core as mx
import numpy as np
from fastapi import FastAPI
from mlx_embeddings import generate, load
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "mlx-community/bge-small-en-v1.5-4bit")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))

_model = None
_tokenizer = None


def load_model():
    global _model, _tokenizer
    if _model is not None:
        return _model, _tokenizer
    logger.info(f"Loading MLX embedding model: {MODEL_NAME}")
    _model, _tokenizer = load(MODEL_NAME)
    mx.eval(_model.parameters())
    logger.info("Model loaded successfully")
    return _model, _tokenizer


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
    model, tokenizer = load_model()
    result = generate(model, tokenizer, texts=req.texts)
    mx.eval(result.text_embeds)
    embeddings = np.array(result.text_embeds).tolist()
    return EmbedResponse(embeddings=embeddings)
