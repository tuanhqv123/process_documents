"""
LineCell wired table extractor using OpenCV line detection.

Based on:
- PdfTable paper (2409.05125v1): LineCell algorithm for wired tables
- DEXTER paper (2207.06823): Parameterized kernels + coloured table detection

Pipeline:
  1. Detect table type: wired / coloured / wireless
  2. Normalize coloured backgrounds → grayscale
  3. Otsu binarize + invert
  4. Extract H/V lines via parameterized erosion+dilation kernels
  5. Find cell contours from combined lines image
  6. Assign (row, col) grid positions
  7. Detect merged cells (missing interior lines → rowspan/colspan)
  8. OCR each cell with RapidOCR
  9. Build HTML table
"""
from __future__ import annotations

import cv2
import numpy as np
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Cell:
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
# Table type detection
# ---------------------------------------------------------------------------

def detect_table_type(gray: np.ndarray) -> str:
    """
    Classify table image as 'wired', 'coloured', or 'wireless'.

    DEXTER paper Section 2.2:
    - Coloured: ratio of 2nd-highest to highest intensity in histogram > threshold
    - Wired: has H and V lines detected
    - Wireless: no lines found
    """
    h, w = gray.shape

    # --- Coloured detection (DEXTER §2.2) ---
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
    # Find top-2 non-zero intensity peaks
    nonzero = [(i, v) for i, v in enumerate(hist) if v > 0]
    if len(nonzero) >= 2:
        sorted_bins = sorted(nonzero, key=lambda x: -x[1])
        ratio = sorted_bins[1][1] / (sorted_bins[0][1] + 1e-6)
        if ratio > 0.15:
            return "coloured"

    # --- Line detection ---
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    h_lines = _extract_lines(binary, direction="h", ratio=0.3)
    v_lines = _extract_lines(binary, direction="v", ratio=0.3)

    h_count = np.count_nonzero(h_lines)
    v_count = np.count_nonzero(v_lines)

    if h_count > (h * w * 0.005) and v_count > (h * w * 0.005):
        return "wired"

    return "wireless"


# ---------------------------------------------------------------------------
# Line extraction (DEXTER §2.2 parameterized kernels)
# ---------------------------------------------------------------------------

def _extract_lines(binary: np.ndarray, direction: str, ratio: float = 0.3) -> np.ndarray:
    """
    Extract horizontal or vertical lines using parameterized erosion+dilation.

    DEXTER equations (3) and (4):
        Tabhr = (Tab' ⊖ Khr) ⊕ Khr
        Tabvr = (Tab' ⊖ Kvr) ⊕ Kvr
    where Khr = 1 × int(W*ratio), Kvr = int(H*ratio) × 1
    """
    h, w = binary.shape
    if direction == "h":
        ksize = max(20, int(w * ratio))
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (ksize, 1))
    else:
        ksize = max(20, int(h * ratio))
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, ksize))

    eroded = cv2.erode(binary, kernel)
    dilated = cv2.dilate(eroded, kernel)
    return dilated


# ---------------------------------------------------------------------------
# Background normalization for coloured tables
# ---------------------------------------------------------------------------

def _normalize_colour(img_bgr: np.ndarray) -> np.ndarray:
    """
    Convert coloured background cells to white so line detection can work.
    Uses HSV: pixels with high value (bright) and any saturation → white.
    """
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    # Coloured backgrounds: saturation > 20 and value > 100
    mask = (hsv[:, :, 1] > 20) & (hsv[:, :, 2] > 100)
    out = img_bgr.copy()
    out[mask] = [255, 255, 255]
    return out


# ---------------------------------------------------------------------------
# Grid reconstruction from lines
# ---------------------------------------------------------------------------

def _get_grid_lines(binary: np.ndarray, ratio: float = 0.3):
    """Return (h_lines_img, v_lines_img, combined_img)."""
    h_img = _extract_lines(binary, "h", ratio)
    v_img = _extract_lines(binary, "v", ratio)
    combined = cv2.bitwise_or(h_img, v_img)
    # Thicken lines slightly for robust contour finding
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    combined = cv2.dilate(combined, kernel, iterations=1)
    return h_img, v_img, combined


def _find_cells_from_lines(combined: np.ndarray) -> list[tuple[int, int, int, int]]:
    """
    Find cell bounding boxes from combined H+V lines image.

    For bordered tables: contours of filled regions between lines = cells.
    Returns list of (x1, y1, x2, y2).
    """
    # Invert: cells are the white spaces enclosed by lines
    inverted = cv2.bitwise_not(combined)
    contours, _ = cv2.findContours(inverted, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    h, w = combined.shape
    min_area = (h * w) * 0.0005  # ignore tiny noise contours
    max_area = (h * w) * 0.98    # ignore full-image contour

    cells = []
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        area = cw * ch
        if min_area < area < max_area:
            cells.append((x, y, x + cw, y + ch))

    return cells


def _assign_grid(cells: list[tuple]) -> list[Cell]:
    """
    Assign (row, col) to each cell bbox by clustering x/y coordinates.
    Uses sorted unique thresholded coordinates.
    """
    if not cells:
        return []

    # Get all y1, y2, x1, x2 edges
    ys = sorted(set([c[1] for c in cells] + [c[3] for c in cells]))
    xs = sorted(set([c[0] for c in cells] + [c[2] for c in cells]))

    def snap(vals, targets, tol=8):
        """Snap values to nearest target within tolerance."""
        result = []
        for v in vals:
            closest = min(targets, key=lambda t: abs(t - v))
            if abs(closest - v) <= tol:
                result.append(closest)
            else:
                result.append(v)
        return result

    def coord_to_idx(val, sorted_unique, tol=8):
        for i, u in enumerate(sorted_unique):
            if abs(val - u) <= tol:
                return i
        return -1

    grid_cells = []
    for (x1, y1, x2, y2) in cells:
        row = coord_to_idx(y1, ys)
        col = coord_to_idx(x1, xs)
        row2 = coord_to_idx(y2, ys)
        col2 = coord_to_idx(x2, xs)
        if row < 0 or col < 0:
            continue
        rowspan = max(1, row2 - row)
        colspan = max(1, col2 - col)
        grid_cells.append(Cell(
            row=row, col=col,
            rowspan=rowspan, colspan=colspan,
            x1=x1, y1=y1, x2=x2, y2=y2,
        ))

    return grid_cells


# ---------------------------------------------------------------------------
# OCR per cell
# ---------------------------------------------------------------------------

def _ocr_cells(img_bgr: np.ndarray, cells: list[Cell], ocr) -> list[Cell]:
    """Run RapidOCR on each cell crop and fill cell.text."""
    h, w = img_bgr.shape[:2]
    for cell in cells:
        # Add small padding
        pad = 3
        x1 = max(0, cell.x1 + pad)
        y1 = max(0, cell.y1 + pad)
        x2 = min(w, cell.x2 - pad)
        y2 = min(h, cell.y2 - pad)
        if x2 <= x1 or y2 <= y1:
            continue
        crop = img_bgr[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        try:
            result, _ = ocr(crop)
            if result:
                texts = [r[1] for r in result if r[1]]
                cell.text = " ".join(texts).strip()
        except Exception:
            pass
    return cells


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

def _build_html(cells: list[Cell]) -> str:
    """Build HTML table from grid cells with rowspan/colspan."""
    if not cells:
        return ""

    n_rows = max(c.row + c.rowspan for c in cells)
    n_cols = max(c.col + c.colspan for c in cells)

    # Build lookup: (row, col) → Cell (for occupied slots)
    occupied: set[tuple[int, int]] = set()
    cell_map: dict[tuple[int, int], Cell] = {}
    for cell in cells:
        cell_map[(cell.row, cell.col)] = cell
        for r in range(cell.row, cell.row + cell.rowspan):
            for c in range(cell.col, cell.col + cell.colspan):
                occupied.add((r, c))

    rows_html = []
    for r in range(n_rows):
        cols_html = []
        for c in range(n_cols):
            if (r, c) not in cell_map:
                continue  # spanned slot, skip
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

def extract_wired_table(image_path: str, ocr=None) -> str | None:
    """
    Extract a wired or coloured table from an image using OpenCV line detection.

    Returns HTML string if successful, None if the table appears wireless
    or extraction fails.

    Args:
        image_path: Path to the table image.
        ocr: RapidOCR instance (optional, will be lazy-loaded if None).
    """
    img_bgr = cv2.imread(image_path)
    if img_bgr is None:
        return None

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    table_type = detect_table_type(gray)

    if table_type == "wireless":
        return None  # let RapidTable handle it

    # Normalize coloured backgrounds before line extraction
    work_img = img_bgr
    if table_type == "coloured":
        work_img = _normalize_colour(img_bgr)

    work_gray = cv2.cvtColor(work_img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(work_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    h_img, v_img, combined = _get_grid_lines(binary, ratio=0.3)

    cell_bboxes = _find_cells_from_lines(combined)
    if len(cell_bboxes) < 2:
        return None  # not enough cells found

    grid_cells = _assign_grid(cell_bboxes)
    if not grid_cells:
        return None

    # Filter out single-cell results (whole table as one cell)
    unique_rows = len(set(c.row for c in grid_cells))
    unique_cols = len(set(c.col for c in grid_cells))
    if unique_rows < 2 or unique_cols < 2:
        return None

    # Lazy-load OCR
    if ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        ocr = RapidOCR()

    grid_cells = _ocr_cells(work_img, grid_cells, ocr)

    html = _build_html(grid_cells)
    if not html or html == "<table></table>":
        return None

    return html
