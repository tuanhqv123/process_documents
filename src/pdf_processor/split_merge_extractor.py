"""
Rule-based Split-Merge table extractor.

Based on:
- Viblo blog "Simple is better than complex" (Deep Split-Merge architecture)
- DEXTER paper (2207.06823): parameterized separator detection

Works for tables WITHOUT visible vertical grid lines:
- Colour-banded tables (POS table)
- Partially-bordered tables with only H-lines (B/A matrices)
- Borderless tables where columns are defined by text alignment

Pipeline:
  1. SPLIT rows: detect row boundaries via dark lines + uniform colour bands
  2. SPLIT cols: detect column boundaries by clustering OCR text x-positions
  3. BUILD GRID: create (row, col) cell grid from boundaries
  4. OCR per cell: crop each cell → RapidOCR text
  5. MERGE: detect spanning cells (wide text bbox covers multiple columns)
  6. BUILD HTML
"""
from __future__ import annotations

import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SplitCell:
    row: int
    col: int
    rowspan: int = 1
    colspan: int = 1
    x1: int = 0
    y1: int = 0
    x2: int = 0
    y2: int = 0
    text: str = ""


# ---------------------------------------------------------------------------
# SPLIT — row boundary detection
# ---------------------------------------------------------------------------

def _detect_row_boundaries(gray: np.ndarray) -> list[int]:
    """
    Detect row separator y-positions using two strategies:
    1. Dark lines (>50% pixels with gray < 80) — hard borders
    2. Uniform colour bands (std < 6, mean > 170) — light separator bands

    Returns sorted list of y-coordinate boundaries.
    """
    h, w = gray.shape

    # Strategy 1: dark lines
    dark_ys = []
    for y in range(h):
        if np.mean(gray[y, :] < 80) > 0.5:
            dark_ys.append(y)

    # Strategy 2: uniform colour bands
    band_ys = []
    in_band = False
    for y in range(h):
        row = gray[y, max(0, w // 10): w - w // 10]  # ignore edges
        if np.std(row) < 6 and np.mean(row) > 170:
            if not in_band:
                band_ys.append(y)
            in_band = True
        else:
            in_band = False

    all_ys = sorted(set(dark_ys + band_ys))
    if not all_ys:
        return [0, h]

    # Cluster nearby positions (within 4px → same boundary)
    merged = [all_ys[0]]
    for y in all_ys[1:]:
        if y - merged[-1] > 4:
            merged.append(y)

    # Always include image top and bottom
    if merged[0] > 2:
        merged.insert(0, 0)
    if merged[-1] < h - 2:
        merged.append(h)

    return merged


# ---------------------------------------------------------------------------
# SPLIT — column boundary detection via OCR text clustering
# ---------------------------------------------------------------------------

def _detect_col_boundaries(img_bgr: np.ndarray, ocr,
                            row_bounds: list[int]) -> list[int]:
    """
    Detect column boundaries by running OCR on the header row.

    Strategy (from Split-Merge / DEXTER):
    1. Find the header row (first non-separator, non-black row)
    2. Run OCR on that row to get individual column header text bboxes
    3. Use bbox centres as column centres
    4. Boundaries = midpoints between consecutive centres

    Falls back to full-image OCR clustering if header approach fails.
    """
    h, w = img_bgr.shape[:2]

    # Find first content row (skip thin separators and black header bands)
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    header_y1, header_y2 = 0, h
    for i in range(len(row_bounds) - 1):
        y1, y2 = row_bounds[i], row_bounds[i + 1]
        if y2 - y1 < 15:  # skip thin separator lines (< 15px)
            continue
        band = gray[y1:y2, :]
        # Skip all-black rows (caption bands)
        if np.mean(band < 60) > 0.4:
            continue
        header_y1, header_y2 = y1, y2
        break

    # Run OCR on full image once, then filter to header row boxes
    # (better than cropping: small crops lose OCR accuracy)
    try:
        full_result, _ = ocr(img_bgr)
    except Exception:
        full_result = []

    col_centers = _header_col_centers(full_result, header_y1, header_y2, w)

    # If header didn't give enough columns, fall back to top-quarter OCR
    if len(col_centers) < 2:
        col_centers = _full_image_col_centers(img_bgr, ocr, w)

    if len(col_centers) < 2:
        return [0, w]

    col_centers = sorted(col_centers)

    # Check if there's a label column to the left of the leftmost header column.
    # Some tables have row-label columns with no column header text.
    leftmost = col_centers[0]
    if leftmost > w * 0.15:  # first header starts far from left edge
        # Look for text in data rows that's significantly left of the first header
        label_xs = []
        for box, text, conf in full_result:
            if not text or float(conf) < 0.5:
                continue
            ys = [p[1] for p in box]
            if min(ys) < header_y2 + 5:  # skip header row itself
                continue
            xs = [p[0] for p in box]
            cx = (min(xs) + max(xs)) / 2
            if cx < leftmost - (col_centers[1] - col_centers[0]) * 0.4:
                label_xs.append(cx)
        if label_xs:
            label_center = float(np.mean(label_xs))
            col_centers.insert(0, label_center)

    # Build boundaries as midpoints between column centres
    boundaries = [0]
    for i in range(len(col_centers) - 1):
        mid = int((col_centers[i] + col_centers[i + 1]) / 2)
        boundaries.append(mid)
    boundaries.append(w)

    return boundaries


def _header_col_centers(result, header_y1: int, header_y2: int, w: int) -> list[float]:
    """Extract column centers from full-image OCR result filtered to header y-range."""
    if not result:
        return []
    centers = []
    margin = 5  # small tolerance for OCR bbox imprecision
    for box, text, conf in result:
        if not text or float(conf) < 0.5:
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        # Box must overlap with header row (strict — avoid data rows bleeding in)
        box_y1, box_y2 = min(ys), max(ys)
        if box_y2 < header_y1 - margin or box_y1 > header_y2 + margin:
            continue
        centers.append((min(xs) + max(xs)) / 2)
    return _cluster_1d(centers, gap=20)


def _ocr_col_centers(crop: np.ndarray, ocr, full_w: int) -> list[float]:
    """Run OCR on a single-row crop, return x-midpoints of detected text."""
    try:
        result, _ = ocr(crop)
    except Exception:
        return []
    if not result:
        return []

    centers = []
    for box, text, conf in result:
        if not text or float(conf) < 0.5:
            continue
        xs = [p[0] for p in box]
        centers.append((min(xs) + max(xs)) / 2)

    # Cluster nearby centres (within 20px = same column label)
    return _cluster_1d(centers, gap=20)


def _full_image_col_centers(img_bgr: np.ndarray, ocr, w: int) -> list[float]:
    """Fallback: OCR top quarter of image to find column header positions."""
    h = img_bgr.shape[0]
    # Only use top quarter to avoid data row numbers polluting column detection
    top_crop = img_bgr[:max(h // 4, 60), :]
    try:
        result, _ = ocr(top_crop)
    except Exception:
        return []
    if not result:
        return []

    x_mids = []
    for box, text, conf in result:
        if not text or float(conf) < 0.5:
            continue
        xs = [p[0] for p in box]
        x_mids.append((min(xs) + max(xs)) / 2)

    return _cluster_1d(x_mids, gap=w // 15)


def _find_peaks(arr: np.ndarray, min_prominence: float = 0.3) -> list[int]:
    """Find local maxima in 1D array above threshold."""
    threshold = arr.max() * min_prominence
    peaks = []
    for i in range(1, len(arr) - 1):
        if arr[i] >= threshold and arr[i] >= arr[i - 1] and arr[i] >= arr[i + 1]:
            # Check it's a local peak in a window
            if not peaks or i - peaks[-1] > 5:
                peaks.append(i)
    return peaks


def _cluster_1d(values: list[float], gap: float) -> list[float]:
    """Cluster 1D values by gap threshold, return cluster centres."""
    if not values:
        return []
    sorted_vals = sorted(values)
    clusters = [[sorted_vals[0]]]
    for v in sorted_vals[1:]:
        if v - clusters[-1][-1] > gap:
            clusters.append([])
        clusters[-1].append(v)
    return [float(np.mean(c)) for c in clusters]


# ---------------------------------------------------------------------------
# BUILD GRID + OCR per cell
# ---------------------------------------------------------------------------

def _build_cells(img_bgr: np.ndarray, row_bounds: list[int],
                 col_bounds: list[int], ocr) -> list[SplitCell]:
    """
    Build grid cells using column-strip OCR + 3-rule box assignment.

    Root cause of cross-column merging: OCR detection models treat adjacent
    column values as one text region when printed close together.

    Fix: OCR each column strip independently with right-side padding to avoid
    truncation, then assign text to rows via center-point.

    Paper rules (ICDAR 2021, section 2.4):
      Rule 1 - Center Point: text center inside cell -> assign
      Rule 2 - IOU: pick cell with highest IOU
      Rule 3 - Distance: pick nearest cell center
    """
    h, w = img_bgr.shape[:2]
    # Right-side padding scales with column width so wide numbers aren't truncated.
    # min_inner filter (below) still rejects overflow artifacts from the previous col.

    # Build grid of empty cells
    grid: dict[tuple[int, int], SplitCell] = {}
    row_idx = 0
    for y1, y2 in zip(row_bounds[:-1], row_bounds[1:]):
        if y2 - y1 < 8:
            continue
        col_idx = 0
        for x1, x2 in zip(col_bounds[:-1], col_bounds[1:]):
            if x2 - x1 < 5:
                continue
            grid[(row_idx, col_idx)] = SplitCell(
                row=row_idx, col=col_idx,
                x1=x1, y1=y1, x2=x2, y2=y2,
            )
            col_idx += 1
        row_idx += 1

    if not grid:
        return []

    cells_list = list(grid.values())

    # OCR each column strip to prevent cross-column text merging.
    # Right-pad each strip so text near the right boundary is not truncated.
    # Filter to boxes whose center-x falls within the column's original range.
    for ci, (col_x1, col_x2) in enumerate(zip(col_bounds[:-1], col_bounds[1:])):
        if col_x2 - col_x1 < 5:
            continue
        PAD = max(30, int((col_x2 - col_x1) * 0.5))  # dynamic: wider cols need more padding
        strip_x2 = min(w, col_x2 + PAD)
        strip = img_bgr[:, col_x1:strip_x2]
        try:
            result, _ = ocr(strip)
        except Exception:
            result = []
        if not result:
            continue

        col_cells = [c for c in cells_list if c.x1 == col_x1]

        for box, text, conf in result:
            if not text or float(conf) < 0.5:
                continue
            xs = [p[0] + col_x1 for p in box]  # absolute coords
            ys = [p[1] for p in box]
            tx1, tx2 = min(xs), max(xs)
            ty1, ty2 = min(ys), max(ys)
            cx = (tx1 + tx2) / 2
            cy = (ty1 + ty2) / 2

            # Reject text from the right-padding zone (belongs to next column)
            if not (col_x1 <= cx < col_x2):
                continue

            # Reject overflow from the previous column's right edge.
            # When a wide number spills past col_x1, OCR detects the
            # visible portion starting right at the strip boundary.
            # Real content in this column starts well inside col_x1,
            # not within the first ~15% of the column width.
            min_inner = int((col_x2 - col_x1) * 0.15)
            if col_x1 > 0 and tx1 < col_x1 + min_inner:
                continue

            # Rule 1: Center Point
            center_cell = next(
                (c for c in col_cells
                 if c.x1 <= cx < c.x2 and c.y1 <= cy < c.y2),
                None
            )
            if center_cell is not None:
                _append_text(center_cell, text)
                continue

            # Rule 2: IOU (within this column only)
            best_cell = None
            best_iou = 0.0
            tb_area = max((tx2 - tx1) * (ty2 - ty1), 1)
            for cell in col_cells:
                ix = max(0, min(tx2, cell.x2) - max(tx1, cell.x1))
                iy = max(0, min(ty2, cell.y2) - max(ty1, cell.y1))
                inter = ix * iy
                if inter == 0:
                    continue
                cell_area = max((cell.x2 - cell.x1) * (cell.y2 - cell.y1), 1)
                iou = inter / (tb_area + cell_area - inter)
                if iou > best_iou:
                    best_iou = iou
                    best_cell = cell
            if best_cell is not None and best_iou > 0:
                _append_text(best_cell, text)
                continue

            # Rule 3: Distance (within this column only)
            if col_cells:
                best_cell = min(
                    col_cells,
                    key=lambda c: (((c.x1 + c.x2) / 2 - cx) ** 2
                                   + ((c.y1 + c.y2) / 2 - cy) ** 2)
                )
                _append_text(best_cell, text)

    return cells_list


def _append_text(cell: SplitCell, text: str) -> None:
    """Append text to a cell, space-separated."""
    t = text.strip()
    if t:
        cell.text = (cell.text + " " + t).strip() if cell.text else t


def _split_text_to_cols(text: str, spanned_cols: list[SplitCell],
                        tx1: float, tx2: float) -> None:
    """
    Distribute text tokens across spanned columns.

    Implements the paper's box-assignment idea at the sub-token level:
    when an OCR box spans N columns, split its text into N parts and
    assign each part to the corresponding column.

    Token extraction priority:
    1. Decimal numbers (handles OCR merging "0.0453" + "0.0449" → "0.04530.0449")
    2. Whitespace-separated tokens
    3. Proportional split as fallback
    """
    import re
    spanned_cols = sorted(spanned_cols, key=lambda c: c.x1)
    n_cols = len(spanned_cols)

    # Strategy 1: Extract decimal numbers (catches concatenated floats like "0.04530.0449")
    # Pattern: a decimal number is digits optionally preceded by digits, then ".", then digits
    # We use a greedy left-to-right scan to avoid partial-match issues
    decimal_tokens = re.findall(r'\d+\.\d+', text)
    if len(decimal_tokens) >= n_cols:
        # Distribute: first n_cols numbers go to respective columns
        for col, token in zip(spanned_cols, decimal_tokens[:n_cols]):
            _append_text(col, token)
        return

    # Strategy 2: Split by whitespace
    ws_tokens = text.split()
    if len(ws_tokens) == n_cols:
        for col, token in zip(spanned_cols, ws_tokens):
            _append_text(col, token)
        return

    if 1 < len(ws_tokens) <= n_cols * 2:
        # More tokens than columns: distribute by estimated character position
        span_w = max(tx2 - tx1, 1)
        char_w = span_w / max(len(text), 1)
        pos = 0
        for token in ws_tokens:
            token_cx = tx1 + (pos + len(token) / 2) * char_w
            target = min(spanned_cols, key=lambda c: abs((c.x1 + c.x2) / 2 - token_cx))
            _append_text(target, token)
            pos += len(token) + 1
        return

    # Strategy 3: Give full text to column with maximum overlap
    best = max(spanned_cols, key=lambda c: min(tx2, c.x2) - max(tx1, c.x1))
    _append_text(best, text)


# ---------------------------------------------------------------------------
# MERGE — spanning cell detection
# ---------------------------------------------------------------------------

def _detect_spans(cells: list[SplitCell], img_bgr: np.ndarray,
                  ocr, row_bounds: list[int],
                  col_bounds: list[int]) -> list[SplitCell]:
    """
    Detect spanning cells by running OCR on the full image and checking
    if any text bbox covers multiple columns or rows.

    For each OCR box that spans more than 1 column width → colspan.
    For each OCR box that spans more than 1 row height → rowspan.
    """
    try:
        result, _ = ocr(img_bgr)
    except Exception:
        return cells

    if not result:
        return cells

    col_widths = [col_bounds[i + 1] - col_bounds[i]
                  for i in range(len(col_bounds) - 1)]
    if not col_widths:
        return cells
    avg_col_w = np.mean(col_widths)

    row_heights = [row_bounds[i + 1] - row_bounds[i]
                   for i in range(len(row_bounds) - 1)]
    if not row_heights:
        return cells
    avg_row_h = np.mean(row_heights)

    # Build cell lookup
    cell_map: dict[tuple[int, int], SplitCell] = {
        (c.row, c.col): c for c in cells
    }

    for box, text, conf in result:
        if not text or float(conf) < 0.6:
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        bx1, bx2 = min(xs), max(xs)
        by1, by2 = min(ys), max(ys)
        bw = bx2 - bx1
        bh = by2 - by1

        # Determine which cell this bbox starts in
        start_row = _find_interval(by1, row_bounds)
        start_col = _find_interval(bx1, col_bounds)
        if start_row < 0 or start_col < 0:
            continue

        # Estimate colspan/rowspan
        colspan = max(1, round(bw / avg_col_w))
        rowspan = max(1, round(bh / avg_row_h))

        if colspan > 1 or rowspan > 1:
            key = (start_row, start_col)
            if key in cell_map:
                cell = cell_map[key]
                # Only set colspan if the cells it would cover are actually empty.
                # If column-strip OCR already filled them, this is a false span
                # caused by OCR merging adjacent text in the full-image pass.
                if colspan > cell.colspan:
                    actual_span = min(colspan, len(col_bounds) - 1 - start_col)
                    spanned_have_text = any(
                        cell_map.get((start_row, start_col + dc), SplitCell(0, 0)).text
                        for dc in range(1, actual_span)
                    )
                    if not spanned_have_text:
                        cell.colspan = actual_span
                if rowspan > cell.rowspan:
                    actual_rspan = min(rowspan, len(row_bounds) - 1 - start_row)
                    spanned_have_text = any(
                        cell_map.get((start_row + dr, start_col), SplitCell(0, 0)).text
                        for dr in range(1, actual_rspan)
                    )
                    if not spanned_have_text:
                        cell.rowspan = actual_rspan
                # Update text if empty
                if not cell.text:
                    cell.text = text

    return cells


def _find_interval(val: float, bounds: list[int]) -> int:
    """Find which interval [bounds[i], bounds[i+1]) contains val."""
    for i in range(len(bounds) - 1):
        if bounds[i] <= val < bounds[i + 1]:
            return i
    return -1


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

def _build_html(cells: list[SplitCell]) -> str:
    """Build HTML table from grid cells."""
    if not cells:
        return ""

    n_rows = max(c.row + c.rowspan for c in cells)
    n_cols = max(c.col + c.colspan for c in cells)

    # Track occupied slots
    occupied: set[tuple[int, int]] = set()
    cell_map: dict[tuple[int, int], SplitCell] = {}

    for cell in cells:
        if (cell.row, cell.col) not in occupied:
            cell_map[(cell.row, cell.col)] = cell
            for r in range(cell.row, cell.row + cell.rowspan):
                for c in range(cell.col, cell.col + cell.colspan):
                    occupied.add((r, c))

    rows_html = []
    for r in range(n_rows):
        cols_html = []
        for c in range(n_cols):
            if (r, c) not in cell_map:
                continue
            cell = cell_map[(r, c)]
            attrs = ""
            if cell.rowspan > 1:
                attrs += f' rowspan="{cell.rowspan}"'
            if cell.colspan > 1:
                attrs += f' colspan="{cell.colspan}"'
            text = cell.text.replace("<", "&lt;").replace(">", "&gt;")
            cols_html.append(f"<td{attrs}>{text}</td>")
        if cols_html:
            rows_html.append("<tr>" + "".join(cols_html) + "</tr>")

    if not rows_html:
        return ""
    return "<table>" + "".join(rows_html) + "</table>"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_split_merge(image_path: str, ocr=None) -> str | None:
    """
    Extract table using rule-based Split-Merge approach.

    Best for:
    - Colour-banded tables with no vertical lines (POS table)
    - Partially-bordered tables with only H-lines (B/A matrices)

    Returns HTML string or None if extraction fails.
    """
    img_bgr = cv2.imread(image_path)
    if img_bgr is None:
        return None

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    if ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        ocr = RapidOCR()

    # SPLIT: row boundaries
    row_bounds = _detect_row_boundaries(gray)

    # Filter out header/caption rows (very tall black bands in B matrix)
    # Keep only rows with height >= 15px and not dominated by dark pixels
    filtered_rows = [row_bounds[0]]
    for i in range(len(row_bounds) - 1):
        y1, y2 = row_bounds[i], row_bounds[i + 1]
        row_h = y2 - y1
        if row_h < 8:
            continue
        band = gray[y1:y2, :]
        if np.mean(band < 60) > 0.4:  # skip black header bands
            continue
        if filtered_rows[-1] != y1:
            filtered_rows.append(y1)
        filtered_rows.append(y2)

    # Deduplicate
    row_bounds = sorted(set(filtered_rows))
    if len(row_bounds) < 3:
        return None

    # SPLIT: column boundaries
    col_bounds = _detect_col_boundaries(img_bgr, ocr, row_bounds)
    if len(col_bounds) < 3:
        return None

    # BUILD GRID + OCR
    cells = _build_cells(img_bgr, row_bounds, col_bounds, ocr)
    if not cells:
        return None

    # Validate: need at least 2 rows × 2 cols of content
    content_rows = len(set(c.row for c in cells if c.text))
    content_cols = len(set(c.col for c in cells if c.text))
    if content_rows < 2 or content_cols < 2:
        return None

    # MERGE: detect spanning cells
    cells = _detect_spans(cells, img_bgr, ocr, row_bounds, col_bounds)

    html = _build_html(cells)
    if not html or html == "<table></table>":
        return None

    return html
