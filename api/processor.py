"""
Background PDF processing — process all then save.
"""

import os
import sys
import threading
import traceback
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Generator

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from api.db import get_session, Document, Chunk, DocImage, Formula
from .pipeline import PDFPipeline, PipelineConfig
from .embedding_client import embedding_client


@dataclass
class ProcessResult:
    chunks: list[dict]
    images: list[dict]
    formulas: list[dict]
    total_pages: int


def process_document(doc_id: int, file_path: str, image_output_dir: str):
    """Run in a background thread."""
    db = get_session()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return
        
        doc.status = "processing"
        db.commit()
        
        result = _run(doc_id, file_path, image_output_dir)
        
        _save_all(db, doc_id, result)
        
        _embed_chunks(db, doc_id)
        
        doc = db.query(Document).filter(Document.id == doc_id).first()
        doc.status = "ready"
        doc.page_count = result.total_pages
        doc.chunk_count = len(result.chunks)
        doc.image_count = len(result.images)
        doc.formula_count = len(result.formulas)
        db.commit()
    except Exception as e:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.status = "error"
            doc.error = str(e)
            db.commit()
        traceback.print_exc()
    finally:
        db.close()


def _run(doc_id: int, file_path: str, image_output_dir: str) -> ProcessResult:
    config = PipelineConfig(image_output_dir=image_output_dir)
    pipeline = PDFPipeline(file_path, config)
    
    chunks = []
    images = []
    formulas = []
    
    total_pages = pipeline.page_count()
    
    for page_result in pipeline.process_pages(doc_id):
        if page_result.markdown and page_result.markdown.strip():
            chunks.append({
                "chunk_index": len(chunks),
                "text": page_result.markdown,
                "page_start": page_result.page_num,
                "page_end": page_result.page_num,
                "section_path": "[]",
                "element_types": '["page"]',
                "html": page_result.html,
            })
        
        for img_data in page_result.images:
            image_path = img_data.get("image_path", "")
            if image_path:
                images.append({
                    "page_num": page_result.page_num,
                    "image_path": image_path,
                    "image_type": img_data.get("image_type", "generic"),
                    "ocr_text": img_data.get("ocr_text", ""),
                    "nearby_text": img_data.get("nearby_text", ""),
                    "bbox": str(img_data.get("bbox", [])),
                })
        
        for latex in page_result.latex_formulas:
            formulas.append({
                "page_num": page_result.page_num,
                "latex": latex,
                "formula_type": "display",
                "bbox": "[]",
            })
    
    return ProcessResult(
        chunks=chunks,
        images=images,
        formulas=formulas,
        total_pages=total_pages,
    )


def _save_all(db: Session, doc_id: int, result: ProcessResult):
    for c in result.chunks:
        chunk = Chunk(
            doc_id=doc_id,
            chunk_index=c["chunk_index"],
            text=c["text"],
            page_start=c["page_start"],
            page_end=c["page_end"],
            section_path=c["section_path"],
            element_types=c["element_types"],
            html=c.get("html", ""),
        )
        db.add(chunk)
    
    for img in result.images:
        doc_image = DocImage(
            doc_id=doc_id,
            page_num=img["page_num"],
            image_path=img["image_path"],
            image_type=img["image_type"],
            ocr_text=img["ocr_text"],
            nearby_text=img["nearby_text"],
            bbox=img["bbox"],
        )
        db.add(doc_image)
    
    for f in result.formulas:
        formula = Formula(
            doc_id=doc_id,
            page_num=f["page_num"],
            latex=f["latex"],
            formula_type=f["formula_type"],
            bbox=f["bbox"],
        )
        db.add(formula)
    
    db.commit()


def _embed_chunks(db, doc_id: int):
    chunks = db.query(Chunk).filter(Chunk.doc_id == doc_id).all()
    if not chunks:
        return
    texts = [c.text for c in chunks]
    try:
        embeddings = embedding_client.embed_texts(texts)
        for chunk, emb in zip(chunks, embeddings):
            chunk.embedding = emb
        db.commit()
    except Exception as e:
        logging.warning(f"Failed to embed chunks for doc {doc_id}: {e}")


def start_processing(doc_id: int, file_path: str, image_output_dir: str):
    """Launch background thread."""
    t = threading.Thread(
        target=process_document,
        args=(doc_id, file_path, image_output_dir),
        daemon=True,
    )
    t.start()
