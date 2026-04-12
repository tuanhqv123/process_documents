"""Routes for document extraction (OCR), training (embedding), and OCR data access."""

import json
import logging
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.db import get_session, Document, Chunk, DocumentNode
from api.models import DocumentOut
from api.services.ocr_llm import (
    ocr_pdf,
    save_ocr_data,
    load_ocr_data,
    get_page_image_path,
    get_pdf_page_count,
    update_ocr_block,
)
from api.services.knowledge_graph import build_graph, embed_leaf_nodes, get_tree
from api.embedding_client import embedding_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["extract"])

# Track running extraction threads: doc_id → cancel_event
_running_extractions: dict[int, threading.Event] = {}


def _get_db():
    db = get_session()
    try:
        yield db
    finally:
        db.close()


def _doc_out(r) -> DocumentOut:
    return DocumentOut(
        id=r.id,
        filename=r.filename,
        file_path=r.file_path,
        file_size=r.file_size or 0,
        page_count=r.page_count or 0,
        image_count=r.image_count or 0,
        chunk_count=r.chunk_count or 0,
        formula_count=r.formula_count or 0,
        status=r.status,
        error=r.error,
        created_at=r.created_at.isoformat() if r.created_at else "",
        extract_progress=r.extract_progress or 0,
        extract_message=r.extract_message,
        extracted_pages=r.extracted_pages or 0,
        total_pages_ocr=r.total_pages_ocr or 0,
        ocr_data_path=r.ocr_data_path,
    )


# ── Extract ────────────────────────────────────────────────────────────────────

@router.post("/{doc_id}/extract", response_model=DocumentOut)
def start_extract(doc_id: int, db: Session = Depends(_get_db)):
    """Start OCR extraction for a document using the dots.ocr model."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    if doc.status == "extracting":
        raise HTTPException(400, "Extraction already in progress")

    file_path = Path(doc.file_path)
    if not file_path.exists():
        raise HTTPException(400, "Document file not found on disk")

    cancel_event = threading.Event()
    _running_extractions[doc_id] = cancel_event

    # Count pages for progress tracking
    file_bytes = file_path.read_bytes()
    is_pptx = file_path.suffix.lower() in (".pptx", ".ppt")
    if is_pptx:
        from api.services.ocr_llm import get_pptx_slide_count
        total_pages = get_pptx_slide_count(file_bytes)
    else:
        total_pages = get_pdf_page_count(file_bytes)

    doc.status = "extracting"
    doc.extract_progress = 0
    doc.extract_message = "Starting OCR..."
    doc.extracted_pages = 0
    doc.total_pages_ocr = total_pages
    doc.error = None
    db.commit()

    def run_extraction():
        thread_db = get_session()
        try:
            _file_bytes = file_path.read_bytes()
            _total = total_pages or 1

            def on_page_done(completed: int, total: int):
                progress = int(completed / total * 100)
                _doc = thread_db.query(Document).filter(Document.id == doc_id).first()
                if _doc:
                    _doc.extract_progress = progress
                    _doc.extracted_pages = completed
                    _doc.extract_message = f"OCR page {completed}/{total}..."
                    thread_db.commit()

            def cancel_check():
                return cancel_event.is_set()

            _file_type = "pptx" if is_pptx else "pdf"
            combined_text, ocr_pages = ocr_pdf(
                _file_bytes,
                doc_id=doc_id,
                on_page_done=on_page_done,
                cancel_check=cancel_check,
                file_type=_file_type,
            )

            if cancel_event.is_set():
                _doc = thread_db.query(Document).filter(Document.id == doc_id).first()
                if _doc:
                    _doc.status = "uploaded"
                    _doc.extract_message = "Extraction cancelled"
                thread_db.commit()
                return

            # Save OCR data JSON
            ocr_path = save_ocr_data(doc_id, ocr_pages)

            _doc = thread_db.query(Document).filter(Document.id == doc_id).first()
            if _doc:
                _doc.status = "extracted"
                _doc.extract_progress = 100
                _doc.extract_message = f"OCR complete — {len(ocr_pages)} pages extracted"
                _doc.extracted_pages = len(ocr_pages)
                _doc.total_pages_ocr = _total
                _doc.page_count = total_pages
                _doc.ocr_data_path = ocr_path
                thread_db.commit()

        except Exception as e:
            logger.error("Extraction failed for doc %d: %s", doc_id, e)
            _doc = thread_db.query(Document).filter(Document.id == doc_id).first()
            if _doc:
                _doc.status = "error"
                _doc.error = str(e)
                _doc.extract_message = f"Error: {e}"
            thread_db.commit()
        finally:
            _running_extractions.pop(doc_id, None)
            thread_db.close()

    t = threading.Thread(target=run_extraction, daemon=True)
    t.start()

    db.refresh(doc)
    return _doc_out(doc)


@router.post("/{doc_id}/extract-cancel")
def cancel_extract(doc_id: int):
    """Cancel a running extraction."""
    ev = _running_extractions.get(doc_id)
    if ev:
        ev.set()
        return {"ok": True, "message": "Cancellation requested"}
    return {"ok": False, "message": "No extraction in progress"}


@router.get("/{doc_id}/extract-status", response_model=DocumentOut)
def extract_status(doc_id: int, db: Session = Depends(_get_db)):
    """Poll extraction progress."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    return _doc_out(doc)


# ── Train ──────────────────────────────────────────────────────────────────────

@router.post("/{doc_id}/train", response_model=DocumentOut)
def train_document(doc_id: int, db: Session = Depends(_get_db)):
    """Build the knowledge graph from extracted OCR layout data and embed leaf nodes.

    This replaces flat page chunking with a hierarchical tree:
        Document → Title → Section-header → Text/Table/Picture/…

    Each leaf node (Text, Table, Picture, etc.) gets an embedding that
    includes its ancestor titles/sections as context, improving RAG quality.
    """
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    if doc.status not in ("extracted", "ready"):
        raise HTTPException(400, f"Cannot train document with status '{doc.status}'. Extract first.")

    ocr_pages = load_ocr_data(doc_id)
    if not ocr_pages:
        raise HTTPException(400, "No OCR data found. Run extraction first.")

    # Build hierarchical knowledge graph from OCR layout
    try:
        build_graph(doc_id, ocr_pages, db)
    except Exception as e:
        logger.error("Graph build failed for doc %d: %s", doc_id, e)
        raise HTTPException(500, f"Graph build failed: {e}")

    # Count leaf nodes
    leaf_count = db.query(DocumentNode).filter(
        DocumentNode.doc_id == doc_id,
        DocumentNode.node_rank == 3,
    ).count()

    # Embed leaf nodes with ancestor context
    embedded_count = embed_leaf_nodes(doc_id, db)
    logger.info("Doc %d: %d leaf nodes, %d embedded", doc_id, leaf_count, embedded_count)

    doc.status = "ready"
    doc.chunk_count = leaf_count
    db.commit()
    db.refresh(doc)
    return _doc_out(doc)


# ── Knowledge Graph ────────────────────────────────────────────────────────────

@router.get("/{doc_id}/graph")
def get_document_graph(doc_id: int, db: Session = Depends(_get_db)):
    """Return the document knowledge graph as a nested tree.

    Structure:
        {
          "id": 1, "category": "Document", "text": "report.pdf",
          "children": [
            {"id": 2, "category": "Title", "text": "Chapter 1", "depth": 1,
             "children": [
               {"id": 3, "category": "Section-header", "text": "1.1 Background", "depth": 2,
                "children": [
                  {"id": 4, "category": "Text", "text": "Lorem ipsum...", "depth": 3, "children": []}
                ]}
             ]}
          ]
        }
    """
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")

    tree = get_tree(doc_id, db)
    if not tree:
        return {"doc_id": doc_id, "tree": None, "message": "No knowledge graph — run Train first"}

    # Count stats
    total_nodes = db.query(DocumentNode).filter(DocumentNode.doc_id == doc_id).count()
    leaf_nodes = db.query(DocumentNode).filter(
        DocumentNode.doc_id == doc_id, DocumentNode.node_rank == 3
    ).count()

    return {
        "doc_id": doc_id,
        "total_nodes": total_nodes,
        "leaf_nodes": leaf_nodes,
        "tree": tree,
    }


# ── OCR Pages data ─────────────────────────────────────────────────────────────

@router.get("/{doc_id}/ocr-pages")
def get_ocr_pages(doc_id: int, db: Session = Depends(_get_db)):
    """Return OCR layout JSON for all extracted pages."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    pages = load_ocr_data(doc_id)
    return {"doc_id": doc_id, "total_pages": doc.page_count, "pages": pages}


@router.get("/{doc_id}/page-image/{page_num}")
def get_page_image(doc_id: int, page_num: int, db: Session = Depends(_get_db)):
    """Serve a rendered page PNG (1-based page number)."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")

    img_path = get_page_image_path(doc_id, page_num)
    if not img_path:
        raise HTTPException(404, f"Page image {page_num} not found")

    # Read dimensions from the OCR data for response headers
    pages = load_ocr_data(doc_id)
    page_data = next((p for p in pages if p.get("page") == page_num), None)
    w = page_data.get("image_width", 0) if page_data else 0
    h = page_data.get("image_height", 0) if page_data else 0

    return FileResponse(
        str(img_path),
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-Image-Width": str(w),
            "X-Image-Height": str(h),
        },
    )


# ── Re-extract single page ────────────────────────────────────────────────────

@router.post("/{doc_id}/extract-page")
def extract_single_page(doc_id: int, page_num: int, db: Session = Depends(_get_db)):
    """Re-OCR a single page and update the saved OCR JSON in place."""
    from api.services.ocr_llm import pdf_pages_to_b64, ocr_single_page, save_ocr_data, load_ocr_data
    from api.config import settings
    from pathlib import Path as _Path

    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    if not doc.ocr_data_path:
        raise HTTPException(400, "No OCR data yet — run full extraction first")

    file_path = _Path(doc.file_path)
    if not file_path.exists():
        raise HTTPException(400, "PDF file not found on disk")

    file_bytes = file_path.read_bytes()
    images_data = pdf_pages_to_b64(file_bytes)
    if page_num < 1 or page_num > len(images_data):
        raise HTTPException(400, f"Page {page_num} out of range (1–{len(images_data)})")

    img_data = images_data[page_num - 1]
    result = ocr_single_page(img_data, page_num)
    if result.get("error"):
        raise HTTPException(500, f"OCR failed: {result['error']}")

    page_data = result["page_data"]
    if not page_data:
        raise HTTPException(500, "OCR returned no data")

    # Merge into existing OCR JSON
    pages = load_ocr_data(doc_id)
    replaced = False
    for i, p in enumerate(pages):
        if p.get("page") == page_num:
            pages[i] = page_data
            replaced = True
            break
    if not replaced:
        pages.append(page_data)
        pages.sort(key=lambda p: p.get("page", 0))

    save_ocr_data(doc_id, pages)
    return {"ok": True, "page": page_num, "page_data": page_data}


# ── Edit OCR block ─────────────────────────────────────────────────────────────

class OcrBlockUpdate(BaseModel):
    page_num: int    # 1-based
    block_idx: int   # index in layout_json array
    text: str


@router.patch("/{doc_id}/ocr-block")
def update_ocr_block_route(doc_id: int, body: OcrBlockUpdate, db: Session = Depends(_get_db)):
    """Edit the text of a specific OCR block in the saved JSON file."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    if not doc.ocr_data_path:
        raise HTTPException(400, "No OCR data found — run extraction first")

    ok = update_ocr_block(doc_id, body.page_num, body.block_idx, body.text)
    if not ok:
        raise HTTPException(404, f"Block {body.block_idx} on page {body.page_num} not found")
    return {"ok": True}
