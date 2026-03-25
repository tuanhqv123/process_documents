"""
Image analysis using RapidOCR with ONNX Runtime.
No custom OpenCV heuristics — just RapidOCR for text extraction.
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
    """Lightweight image OCR using RapidOCR with ONNX Runtime."""

    def __init__(self, use_gpu: bool = False, use_layout_detection: bool = False):
        self._ocr = None

    @property
    def ocr(self):
        if self._ocr is None:
            from rapidocr_onnxruntime import RapidOCR
            self._ocr = RapidOCR()
        return self._ocr

    def analyze(self, image_path: str) -> VisualElement:
        """Run RapidOCR on image and return structured text."""
        try:
            result, _ = self.ocr(image_path)
        except Exception:
            return VisualElement("generic", "", "", 0.0)

        if not result:
            return VisualElement("generic", "", "", 0.0)

        # Collect all recognized text lines
        # RapidOCR returns list of [bbox, text, confidence]
        lines = []
        raw_parts = []
        items = []

        for bbox, text, conf in result:
            if not text.strip():
                continue
            if conf < 0.3:
                continue
            y = bbox[1]
            x = bbox[0]
            items.append((y, x, text.strip(), conf))
            raw_parts.append(text.strip())

        # Sort by y then x for natural reading order
        items.sort(key=lambda t: (round(t[0], -1), t[1]))

        # Group into lines by Y proximity
        if items:
            current_y = items[0][0]
            current_line = []
            for y, x, text, conf in items:
                if abs(y - current_y) > 15:
                    if current_line:
                        lines.append("  ".join(current_line))
                    current_line = [text]
                    current_y = y
                else:
                    current_line.append(text)
            if current_line:
                lines.append("  ".join(current_line))

        structured = "\n".join(lines)
        raw_text = " ".join(raw_parts)

        return VisualElement(
            image_type="generic",
            structured_text=structured,
            raw_ocr_text=raw_text,
            confidence=0.8 if structured else 0.0,
        )
