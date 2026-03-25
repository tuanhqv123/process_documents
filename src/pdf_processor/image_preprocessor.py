from contextlib import contextmanager
from typing import Generator


@contextmanager
def preprocess_for_ocr(image_path: str) -> Generator[str, None, None]:
    # PDF-extracted images are already straight/oriented — no preprocessing needed
    yield image_path


@contextmanager
def preprocess_for_formula(image_path: str) -> Generator[str, None, None]:
    yield image_path


@contextmanager
def preprocess_for_table(image_path: str) -> Generator[str, None, None]:
    yield image_path
