"""
Image analysis using standard PaddleOCR pipelines only.
No custom OpenCV heuristics — just PaddleOCR for text extraction.
Table recognition is handled separately by TableExtractor.
"""

from dataclasses import dataclass, field


@dataclass
class VisualElement:
    image_type: str
    structured_text: str
    raw_ocr_text: str
    confidence: float
    metadata: dict = field(default_factory=dict)


class ImageAnalyzer:
    """Lightweight image OCR using standard PaddleOCR."""

    def __init__(self, use_gpu: bool = False, use_layout_detection: bool = False):
        self._ocr = None

    @property
    def ocr(self):
        if self._ocr is None:
            from paddleocr import PaddleOCR
            self._ocr = PaddleOCR(
                text_detection_model_name="PP-OCRv5_mobile_det",
                text_recognition_model_name="PP-OCRv5_mobile_rec",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        return self._ocr

    def analyze(self, image_path: str) -> VisualElement:
        """Run PaddleOCR on image and return structured text."""
        try:
            output = list(self.ocr.predict(image_path))
        except Exception:
            return VisualElement("generic", "", "", 0.0)

        if not output:
            return VisualElement("generic", "", "", 0.0)

        # Collect all recognized text lines
        lines = []
        raw_parts = []
        for res in output:
            try:
                texts = res.get("rec_texts", [])
                scores = res.get("rec_scores", [])
                boxes = res.get("rec_boxes", [])

                # Group by Y position for reading order
                items = []
                for i, text in enumerate(texts):
                    if not text.strip():
                        continue
                    score = scores[i] if i < len(scores) else 0
                    if score < 0.3:
                        continue
                    y = boxes[i][1] if i < len(boxes) else 0
                    x = boxes[i][0] if i < len(boxes) else 0
                    items.append((y, x, text.strip()))
                    raw_parts.append(text.strip())

                # Sort by y then x for natural reading order
                items.sort(key=lambda t: (round(t[0], -1), t[1]))

                # Group into lines by Y proximity
                if items:
                    current_y = items[0][0]
                    current_line = []
                    for y, x, text in items:
                        if abs(y - current_y) > 15:
                            if current_line:
                                lines.append("  ".join(current_line))
                            current_line = [text]
                            current_y = y
                        else:
                            current_line.append(text)
                    if current_line:
                        lines.append("  ".join(current_line))
            except Exception:
                continue

        structured = "\n".join(lines)
        raw_text = " ".join(raw_parts)

        return VisualElement(
            image_type="generic",
            structured_text=structured,
            raw_ocr_text=raw_text,
            confidence=0.8 if structured else 0.0,
        )
