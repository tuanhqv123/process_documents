# Table extraction from images.
# Primary: TableRecognitionPipelineV2 (PaddleOCR v3, Python 3.12+)
# Fallback: split_merge_extractor for partial-border tables

import re
import numpy as np

from .image_preprocessor import preprocess_for_table


class TableExtractor:

    def __init__(self):
        self._pipeline = None

    @property
    def pipeline(self):
        if self._pipeline is None:
            from paddleocr import TableRecognitionPipelineV2
            # Use English OCR model for better accuracy on English-only documents
            self._pipeline = TableRecognitionPipelineV2(
                wired_table_structure_recognition_model_name="SLANeXt_wired",
                wireless_table_structure_recognition_model_name="SLANeXt_wireless",
                text_detection_model_name="PP-OCRv5_mobile_det",
                text_recognition_model_name="en_PP-OCRv5_mobile_rec",
                use_layout_detection=False,   # images are already cropped tables
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
            )
        return self._pipeline

    def extract(self, image_path: str) -> str:
        with preprocess_for_table(image_path) as path:
            result = self._try_paddle(path)
            if result:
                return result
            return self._try_split_merge(path) or ""

    def _try_paddle(self, image_path: str) -> str | None:
        try:
            output = list(self.pipeline.predict(
                image_path,
                use_table_orientation_classify=False,
            ))
        except Exception:
            return None

        parts = []
        for res in output:
            try:
                for html in res.html.values():
                    rendered = self._render(html)
                    if rendered:
                        parts.append(rendered)
            except Exception:
                continue

        return "\n\n".join(parts) if parts else None

    def _try_split_merge(self, image_path: str) -> str | None:
        try:
            from .split_merge_extractor import extract_split_merge
            return extract_split_merge(image_path)
        except Exception:
            return None

    def _render(self, html: str) -> str:
        # Use HTML for merged cells, markdown for flat tables
        if not html:
            return ""
        has_merge = bool(re.search(r'rowspan|colspan', html, re.IGNORECASE))
        if has_merge:
            return self._clean_html(html)
        return self._to_markdown(html)

    def _clean_html(self, html: str) -> str:
        import html as html_mod

        m = re.search(r'<table[^>]*>(.*?)</table>', html, re.DOTALL | re.IGNORECASE)
        inner = m.group(1) if m else html

        def clean_cell(m):
            tag, content = m.group(1), m.group(2)
            text = re.sub(r'<[^>]+>', ' ', content)
            text = html_mod.unescape(re.sub(r'\s+', ' ', text).strip())
            return f'<{tag}>{text}</{tag[:2]}>'

        inner = re.sub(
            r'<(t[dh][^>]*)>(.*?)</t[dh]>',
            clean_cell,
            inner,
            flags=re.DOTALL | re.IGNORECASE,
        )
        inner = self._drop_caption_rows(inner)

        first = re.search(r'<tr[^>]*>(.*?)</tr>', inner, re.DOTALL | re.IGNORECASE)
        if first and len(re.findall(r'<t[dh][^>]*>', first.group(1), re.IGNORECASE)) <= 1:
            return ""

        return f'<table border="1">{inner}</table>'

    def _drop_caption_rows(self, inner: str) -> str:
        rows = re.findall(r'<tr[^>]*>.*?</tr>', inner, re.DOTALL | re.IGNORECASE)
        if len(rows) < 3:
            return inner
        expected = len(re.findall(r'<t[dh][^>]*>', rows[0], re.IGNORECASE))
        out = []
        for row in rows:
            cells = re.findall(r'<t[dh][^>]*>', row, re.IGNORECASE)
            if len(cells) == 1 and expected > 1:
                if len(re.sub(r'<[^>]+>', '', row).strip()) > 60:
                    continue
            out.append(row)
        return "".join(out)

    def _to_markdown(self, html: str) -> str:
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
        if not rows:
            return ""

        parsed = []
        for row in rows:
            cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.DOTALL)
            cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            if any(cells):
                parsed.append(cells)

        if not parsed or len(parsed[0]) <= 1:
            return ""

        parsed = self._filter_rows(parsed)
        if not parsed:
            return ""

        header = parsed[0]
        lines = [
            '| ' + ' | '.join(header) + ' |',
            '| ' + ' | '.join('---' for _ in header) + ' |',
        ]
        for row in parsed[1:]:
            padded = row + [''] * (len(header) - len(row))
            lines.append('| ' + ' | '.join(padded[:len(header)]) + ' |')
        return '\n'.join(lines)

    def _filter_rows(self, rows: list[list[str]]) -> list[list[str]]:
        if len(rows) < 3:
            return rows
        num_cols = len(rows[0])
        lens = [np.mean([len(c) for c in r if c]) for r in rows[1:] if any(r)]
        median = np.median(lens) if lens else 10
        out = []
        for i, row in enumerate(rows):
            non_empty = sum(1 for c in row if c)
            if i > 0 and max((len(c) for c in row), default=0) > median * 5 and non_empty <= num_cols * 0.4:
                continue
            out.append(row)
        return out
