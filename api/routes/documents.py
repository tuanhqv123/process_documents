"""Document routes: upload, list, get, delete."""

import json
import os
import shutil
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlalchemy.orm import Session

from api.db import get_session, Document, Chunk, DocImage, Formula, WorkspaceDoc
from api.models import DocumentOut, ChunkOut, ImageOut, ImageUpdate, FormulaOut, ChunkUpdate
from api.embedding_client import embedding_client

router = APIRouter(prefix="/api/documents", tags=["documents"])

UPLOADS_DIR = Path("data/uploads")
IMAGES_DIR = Path("data/images")


def _get_db():
    db = get_session()
    try:
        yield db
    finally:
        db.close()


@router.get("", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(_get_db)):
    rows = db.query(Document).order_by(Document.created_at.desc()).all()
    return [_doc_model(r) for r in rows]


@router.post("/upload", response_model=DocumentOut)
async def upload_document(file: UploadFile = File(...), db: Session = Depends(_get_db)):
    ALLOWED_EXT = (".pdf", ".pptx", ".ppt")
    if not file.filename.lower().endswith(ALLOWED_EXT):
        raise HTTPException(400, "Supported formats: PDF, PPTX")

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename).suffix.lower()
    dest = UPLOADS_DIR / file.filename
    counter = 1
    while dest.exists():
        stem = Path(file.filename).stem
        dest = UPLOADS_DIR / f"{stem}_{counter}{ext}"
        counter += 1

    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    file_size = dest.stat().st_size
    
    doc = Document(
        filename=file.filename,
        file_path=str(dest),
        file_size=file_size,
        status="uploaded",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    return _doc_model(doc)


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: int, db: Session = Depends(_get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    return _doc_model(doc)


@router.delete("/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(_get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    try:
        Path(doc.file_path).unlink(missing_ok=True)
    except Exception:
        pass
    try:
        shutil.rmtree(IMAGES_DIR / f"doc_{doc_id}", ignore_errors=True)
    except Exception:
        pass
    # Clean up OCR data
    from pathlib import Path as _Path
    from api.config import settings as _settings
    try:
        shutil.rmtree(_Path(_settings.OCR_IMAGES_DIR) / str(doc_id), ignore_errors=True)
    except Exception:
        pass
    try:
        (_Path(_settings.OCR_DATA_DIR) / f"{doc_id}_ocr.json").unlink(missing_ok=True)
    except Exception:
        pass
    db.delete(doc)
    db.commit()
    return {"ok": True}


@router.get("/{doc_id}/content")
def get_document_content(doc_id: int, db: Session = Depends(_get_db)):
    """Get all content (chunks, images, formulas) for a document."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    
    chunks = db.query(Chunk).filter(Chunk.doc_id == doc_id).order_by(Chunk.chunk_index).all()
    images = db.query(DocImage).filter(DocImage.doc_id == doc_id).order_by(DocImage.page_num, DocImage.id).all()
    formulas = db.query(Formula).filter(Formula.doc_id == doc_id).order_by(Formula.page_num, Formula.id).all()
    
    return {
        "document": _doc_model(doc),
        "chunks": [_chunk_model(r) for r in chunks],
        "images": [_image_model(r) for r in images],
        "formulas": [_formula_model(r) for r in formulas],
    }


@router.get("/{doc_id}/chunks", response_model=list[ChunkOut])
def get_chunks(doc_id: int, db: Session = Depends(_get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    chunks = db.query(Chunk).filter(Chunk.doc_id == doc_id).order_by(Chunk.chunk_index).all()
    return [_chunk_model(r) for r in chunks]


@router.get("/{doc_id}/images", response_model=list[ImageOut])
def get_images(doc_id: int, db: Session = Depends(_get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    images = db.query(DocImage).filter(DocImage.doc_id == doc_id).order_by(DocImage.page_num, DocImage.id).all()
    return [_image_model(r) for r in images]


@router.get("/{doc_id}/formulas", response_model=list[FormulaOut])
def get_formulas(doc_id: int, db: Session = Depends(_get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    formulas = db.query(Formula).filter(Formula.doc_id == doc_id).order_by(Formula.page_num, Formula.id).all()
    return [_formula_model(r) for r in formulas]


@router.get("/{doc_id}/workspaces")
def get_document_workspaces(doc_id: int, db: Session = Depends(_get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    ws_docs = db.query(WorkspaceDoc).filter(WorkspaceDoc.doc_id == doc_id).all()
    return [{"id": wd.workspace_id} for wd in ws_docs]


chunks_router = APIRouter(prefix="/api/chunks", tags=["chunks"])
images_router = APIRouter(prefix="/api/images", tags=["images"])


@chunks_router.patch("/{chunk_id}")
def update_chunk(chunk_id: int, body: ChunkUpdate, db: Session = Depends(_get_db)):
    chunk = db.query(Chunk).filter(Chunk.id == chunk_id).first()
    if not chunk:
        raise HTTPException(404, "Chunk not found")
    chunk.text = body.text
    chunk.is_edited = True
    db.commit()
    try:
        chunk.embedding = embedding_client.embed_single(body.text)
        db.commit()
    except Exception:
        pass
    return {"ok": True}


@images_router.patch("/{image_id}")
def update_image(image_id: int, body: ImageUpdate, db: Session = Depends(_get_db)):
    image = db.query(DocImage).filter(DocImage.id == image_id).first()
    if not image:
        raise HTTPException(404, "Image not found")
    image.ocr_text = body.ocr_text
    image.is_edited = True
    db.commit()
    return {"ok": True}


def _doc_model(r) -> DocumentOut:
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


def _chunk_model(r) -> ChunkOut:
    return ChunkOut(
        id=r.id,
        doc_id=r.doc_id,
        chunk_index=r.chunk_index,
        text=r.text,
        page_start=r.page_start,
        page_end=r.page_end,
        section_path=json.loads(r.section_path or "[]"),
        element_types=json.loads(r.element_types or "[]"),
        is_edited=r.is_edited,
    )


def _image_model(r) -> ImageOut:
    return ImageOut(
        id=r.id,
        doc_id=r.doc_id,
        page_num=r.page_num,
        image_path=r.image_path,
        image_type=r.image_type or "generic",
        ocr_text=r.ocr_text or "",
        nearby_text=r.nearby_text or "",
        is_edited=r.is_edited,
    )


def _formula_model(r) -> FormulaOut:
    return FormulaOut(
        id=r.id,
        doc_id=r.doc_id,
        page_num=r.page_num,
        latex=r.latex,
        formula_type=r.formula_type or "display",
        bbox=json.loads(r.bbox or "[]"),
        is_edited=r.is_edited,
    )
