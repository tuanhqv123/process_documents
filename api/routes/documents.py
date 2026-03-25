"""Document routes: upload, list, get, delete."""

import json
import os
import shutil
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException

from api import db as database
from api.models import DocumentOut, ChunkOut, ImageOut, ChunkUpdate, ImageUpdate
from api.processor import start_processing

router = APIRouter(prefix="/api/documents", tags=["documents"])

UPLOADS_DIR = Path("data/uploads")
IMAGES_DIR = Path("data/images")


@router.get("", response_model=list[DocumentOut])
def list_documents():
    rows = database.list_documents()
    return [_doc_row(r) for r in rows]


@router.post("/upload", response_model=DocumentOut)
async def upload_document(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported")

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    dest = UPLOADS_DIR / file.filename
    counter = 1
    while dest.exists():
        stem = Path(file.filename).stem
        dest = UPLOADS_DIR / f"{stem}_{counter}.pdf"
        counter += 1

    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    file_size = dest.stat().st_size
    doc_id = database.insert_document(file.filename, str(dest), file_size)

    image_output_dir = str(IMAGES_DIR / f"doc_{doc_id}")
    start_processing(doc_id, str(dest), image_output_dir)

    row = database.get_document(doc_id)
    return _doc_row(row)


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: int):
    row = database.get_document(doc_id)
    if not row:
        raise HTTPException(404, "Document not found")
    return _doc_row(row)


@router.delete("/{doc_id}")
def delete_document(doc_id: int):
    row = database.get_document(doc_id)
    if not row:
        raise HTTPException(404, "Document not found")
    try:
        Path(row["file_path"]).unlink(missing_ok=True)
    except Exception:
        pass
    try:
        shutil.rmtree(IMAGES_DIR / f"doc_{doc_id}", ignore_errors=True)
    except Exception:
        pass
    database.delete_document(doc_id)
    return {"ok": True}


@router.get("/{doc_id}/chunks", response_model=list[ChunkOut])
def get_chunks(doc_id: int):
    if not database.get_document(doc_id):
        raise HTTPException(404, "Document not found")
    return [_chunk_row(r) for r in database.get_chunks(doc_id)]


@router.get("/{doc_id}/images", response_model=list[ImageOut])
def get_images(doc_id: int):
    if not database.get_document(doc_id):
        raise HTTPException(404, "Document not found")
    return [_image_row(r) for r in database.get_images(doc_id)]


# ── Workspaces a document belongs to ──────────────────────────────────────────

@router.get("/{doc_id}/workspaces")
def get_document_workspaces(doc_id: int):
    if not database.get_document(doc_id):
        raise HTTPException(404, "Document not found")
    rows = database.get_document_workspaces(doc_id)
    return [{"id": r["id"], "name": r["name"]} for r in rows]


# ── Chunk / Image edit ────────────────────────────────────────────────────────

chunks_router = APIRouter(prefix="/api/chunks", tags=["chunks"])
images_router = APIRouter(prefix="/api/images", tags=["images"])


@chunks_router.patch("/{chunk_id}")
def update_chunk(chunk_id: int, body: ChunkUpdate):
    database.update_chunk_text(chunk_id, body.text)
    return {"ok": True}


@images_router.patch("/{image_id}")
def update_image(image_id: int, body: ImageUpdate):
    database.update_image_ocr(image_id, body.ocr_text)
    return {"ok": True}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _doc_row(r) -> DocumentOut:
    return DocumentOut(
        id=r["id"],
        filename=r["filename"],
        file_path=r["file_path"],
        file_size=r["file_size"] or 0,
        page_count=r["page_count"] or 0,
        image_count=r["image_count"] or 0,
        chunk_count=r["chunk_count"] or 0,
        status=r["status"],
        error=r["error"],
        created_at=r["created_at"],
    )


def _chunk_row(r) -> ChunkOut:
    return ChunkOut(
        id=r["id"],
        doc_id=r["doc_id"],
        chunk_index=r["chunk_index"],
        text=r["text"],
        page_start=r["page_start"],
        page_end=r["page_end"],
        section_path=json.loads(r["section_path"] or "[]"),
        element_types=json.loads(r["element_types"] or "[]"),
        is_edited=bool(r["is_edited"]),
    )


def _image_row(r) -> ImageOut:
    return ImageOut(
        id=r["id"],
        doc_id=r["doc_id"],
        page_num=r["page_num"],
        image_path=r["image_path"],
        image_type=r["image_type"] or "generic",
        ocr_text=r["ocr_text"] or "",
        nearby_text=r["nearby_text"] or "",
        is_edited=bool(r["is_edited"]),
    )
