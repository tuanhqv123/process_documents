import os
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

EMBEDDING_SERVICE_URL = os.getenv("EMBEDDING_SERVICE_URL", "http://host.docker.internal:8001")


class EmbeddingClient:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or EMBEDDING_SERVICE_URL

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            resp = httpx.post(
                f"{self.base_url}/embed",
                json={"texts": texts},
                timeout=120.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["embeddings"]
        except Exception as e:
            logger.error(f"Embedding service error: {e}")
            raise

    def embed_single(self, text: str) -> list[float]:
        results = self.embed_texts([text])
        return results[0]

    def is_healthy(self) -> bool:
        try:
            resp = httpx.get(f"{self.base_url}/health", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False


embedding_client = EmbeddingClient()
