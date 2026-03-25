"""
PDF processing pipeline — page-by-page streaming.

- PyMuPDF: text and image extraction (fast)
- Yields one page at a time so caller can save incrementally
"""

import os
import re
import time
import pymupdf
from dataclasses import dataclass
from typing import Generator

_ZWS = re.compile(r'[\u200b\u200c\u200d\u200e\u200f\ufeff\u00ad]')


@dataclass
class PageResult:
    page_num: int
    markdown: str
    images: list
    time_sec: float

    @property
    def word_count(self) -> int:
        return len(self.markdown.split())


@dataclass
class ExtractedImage:
    page_num: int
    image_path: str
    nearby_text: str


@dataclass
class PipelineConfig:
    image_output_dir: str = "output/images"


class PDFPipeline:

    def __init__(self, file_path: str, config: PipelineConfig | None = None):
        self.file_path = str(file_path)
        self.config = config or PipelineConfig()

    def page_count(self) -> int:
        doc = pymupdf.open(self.file_path)
        count = len(doc)
        doc.close()
        return count

    def process_pages(self) -> Generator[PageResult, None, None]:
        """
        Yield one PageResult at a time.
        Caller can save each to DB immediately — no waiting for whole file.
        """
        doc = pymupdf.open(self.file_path)
        total = len(doc)
        os.makedirs(self.config.image_output_dir, exist_ok=True)

        for page_num in range(total):
            t0 = time.time()

            page = doc[page_num]

            # --- Extract text with PyMuPDF (instant) ---
            text = page.get_text("text")
            markdown = self._clean_text(text)

            # --- Extract images with PyMuPDF (fast) ---
            images = self._extract_images(page, page_num, doc)

            elapsed = round(time.time() - t0, 2)
            print(f"  [Page {page_num + 1}/{total}] {len(markdown)} chars, "
                  f"{len(images)} images, {elapsed}s")

            yield PageResult(
                page_num=page_num,
                markdown=markdown,
                images=images,
                time_sec=elapsed,
            )

        doc.close()

    def _clean_text(self, text: str) -> str:
        text = _ZWS.sub('', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _extract_images(
        self, page, page_num: int, doc
    ) -> list[ExtractedImage]:
        extracted = []
        try:
            page_images = page.get_images(full=True)
        except Exception:
            return []

        for idx, img_info in enumerate(page_images):
            xref = img_info[0]
            try:
                img_data = doc.extract_image(xref)
                if not img_data:
                    continue
                w = img_data.get("width", 0)
                h = img_data.get("height", 0)
                if w < 50 or h < 50:
                    continue

                ext = img_data["ext"]
                image_bytes = img_data["image"]

                output_path = os.path.join(
                    self.config.image_output_dir,
                    f"page{page_num + 1}_img{idx}.{ext}"
                )

                with open(output_path, "wb") as f:
                    f.write(image_bytes)

                nearby_text = self._extract_nearby_text(page, img_info)

                extracted.append(ExtractedImage(
                    page_num=page_num,
                    image_path=output_path,
                    nearby_text=nearby_text
                ))

            except Exception:
                continue

        return extracted

    def _extract_nearby_text(self, page, img_info) -> str:
        try:
            rect = pymupdf.Rect(img_info[0:4])
            words = page.get_text("words", clip=rect)
            text = " ".join(w[4] for w in words)
            return self._clean_text(text)
        except Exception:
            return ""
