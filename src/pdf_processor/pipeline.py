"""
PDF processing pipeline — page-by-page streaming.

- PyMuPDF: image extraction (fast)
- PP-StructureV3: layout + OCR + table recognition per page
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
    def structure_pipeline(self):
        """Lazy-init PP-StructureV3 (heavy, only load once)."""
        if self._structure is None:
            os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
            from paddleocr import PPStructureV3
            self._structure = PPStructureV3(
                text_detection_model_name="PP-OCRv5_mobile_det",
                text_recognition_model_name="PP-OCRv5_mobile_rec",
                layout_detection_model_name="PP-DocLayout-S",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_seal_recognition=False,
                use_formula_recognition=self.config.use_formula_recognition,
                use_chart_recognition=self.config.use_chart_recognition,
            )
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

            # --- Get structured markdown with PP-StructureV3 ---
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
        """Run PP-StructureV3 on a single page."""
        try:
            # page_range is 1-indexed
            output = list(self.structure_pipeline.predict(
                self.file_path,
                page_range=[page_num + 1, page_num + 1],
            ))
            if output:
                md = output[0].markdown
                text = md.get("markdown_texts", "") if isinstance(md, dict) else str(md)
                return self._clean_text(text)
        except Exception as e:
            print(f"  [Page {page_num + 1}] PP-StructureV3 error: {e}")
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
