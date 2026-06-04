# Vietnamese sentence-embedding service (sentence-transformers).
# CPU-only torch: the shared 4090's driver (570 / CUDA 12) doesn't match the
# default CUDA-13 torch wheel, and this model (PhoBERT-base) is small enough for CPU.
FROM python:3.12-slim

WORKDIR /app

# CPU torch first so sentence-transformers doesn't pull the heavy CUDA build
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY embedder/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY embedder/main.py .

ENV EMBEDDING_MODEL=dangvantuan/vietnamese-embedding \
    EMBEDDING_DIM=768

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
