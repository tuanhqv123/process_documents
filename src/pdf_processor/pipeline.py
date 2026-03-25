"""
PDF processing pipeline — page-by-page streaming.

- PyMuPDF: image extraction (fast)
- RapidOCR: OCR for all pages (fast with ONNX Runtime)
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
    images: list  # list of ExtractedImage
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
    use_formula_recognition: bool = False
    use_chart_recognition: bool = False


class PDFPipeline:

    def __init__(self, file_path: str, config: PipelineConfig | None = None):
        self.file_path = str(file_path)
        self.config = config or PipelineConfig()
        self._structure = None

    @property
    def ocr_engine(self):
        """Lazy-init RapidOCR with ONNX Runtime (fast for Mac M2)."""
        if self._structure is None:
            from rapidocr_onnxruntime import RapidOCR
            self._structure = RapidOCR()
        return self._structure

    def page_count(self) -> int:
        doc = pymupdf.open(self.file_path)
        count = len(doc)
        doc.close()
        return count

    def process_pages(self) -> Generator[PageResult, None, None]:
        """
        Yield one PageResult at a time.
        Caller can save each to DB immediately — no waiting for the whole file.
        """
        doc = pymupdf.open(self.file_path)
        total = len(doc)
        os.makedirs(self.config.image_output_dir, exist_ok=True)

        for page_num in range(total):
            t0 = time.time()

            # --- Extract images with PyMuPDF (fast) ---
            page = doc[page_num]
            images = self._extract_images(page, page_num, doc)

            # --- Extract text with RapidOCR ---
            markdown = self._process_page_structure(page_num)

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

    def _process_page_structure(self, page_num: int) -> str:
        """
        Extract text from page using RapidOCR.
        """
        doc = pymupdf.open(self.file_path)
        page = doc[page_num]

        try:
            # Use RapidOCR for OCR
            page_pix = page.get_pixmap()
            img_bytes = page_pix.tobytes("png")
            result, _ = self.ocr_engine(img_bytes)

            if result:
                ocr_text = "\n".join([line[1] for line in result if line[1].strip()])
                return self._clean_text(ocr_text)

        except Exception as e:
            print(f"  [Page {page_num + 1}] OCR error: {e}")
        finally:
            doc.close()

        return ""

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
                filename = f"page{page_num + 1}_img{idx}.{ext}"
                filepath = os.path.join(self.config.image_output_dir, filename)
                with open(filepath, "wb") as f:
                    f.write(img_data["image"])

                nearby = ""
                try:
                    img_rects = page.get_image_rects(xref)
                    if img_rects:
                        rect = img_rects[0]
                        expanded = rect + pymupdf.Rect(-10, -40, 10, 40)
                        nearby = page.get_text("text", clip=expanded).strip()
                        nearby = _ZWS.sub('', nearby)
                except Exception:
                    pass

                extracted.append(ExtractedImage(
                    page_num=page_num,
                    image_path=filepath,
                    nearby_text=nearby[:200],
                ))
            except Exception:
                continue

        return extracted
