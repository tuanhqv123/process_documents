"""Application configuration via environment variables."""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # OpenAI-compatible OCR endpoint (dots.ocr vision model)
    DOTS_OCR_URL: str = os.getenv("DOTS_OCR_URL", "")
    DOTS_OCR_MODEL: str = os.getenv("DOTS_OCR_MODEL", "rednote-hilab/dots.ocr")

    # OpenAI-compatible LLM endpoint (for image description, etc.)
    VLLM_URL: str = os.getenv("VLLM_URL", "")
    VLLM_API_KEY: str = os.getenv("VLLM_API_KEY", "")
    VLLM_MODEL: str = os.getenv("VLLM_MODEL", "")

    # OCR processing
    OCR_PARALLEL_WORKERS: int = int(os.getenv("OCR_PARALLEL_WORKERS", "5"))
    OCR_MAX_RETRIES: int = int(os.getenv("OCR_MAX_RETRIES", "2"))

    # Storage paths
    OCR_DATA_DIR: str = os.getenv("OCR_DATA_DIR", "data/ocr_data")
    OCR_IMAGES_DIR: str = os.getenv("OCR_IMAGES_DIR", "data/ocr_images")
    UPLOADS_DIR: str = os.getenv("UPLOADS_DIR", "data/uploads")


settings = Settings()
