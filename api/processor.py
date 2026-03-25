"""
Background PDF processing — page-by-page streaming.
Each page is saved to DB immediately so the UI can show progress live.
"""

import os
import sys
import json
import threading
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

from api import db as database


def process_document(doc_id: int, file_path: str, image_output_dir: str):
    """Run in a background thread."""
    try:
        database.update_document_status(doc_id, "processing")
        _run(doc_id, file_path, image_output_dir)
    except Exception as e:
        database.update_document_status(doc_id, "error", str(e))
        traceback.print_exc()


def _run(doc_id: int, file_path: str, image_output_dir: str):
    from src.pdf_processor.pipeline import PDFPipeline, PipelineConfig

    config = PipelineConfig(image_output_dir=image_output_dir)
    pipeline = PDFPipeline(file_path, config)

    total_pages = pipeline.page_count()
    chunk_index = 0
    image_count = 0

    # Process page by page — save each immediately
    for page_result in pipeline.process_pages():
        # Save text chunk for this page
        if page_result.markdown:
            chunk_data = {
                "chunk_index": chunk_index,
                "text": page_result.markdown,
                "page_start": page_result.page_num,
                "page_end": page_result.page_num,
                "section_path": [],
                "element_types": ["page"],
            }
            database.insert_chunks(doc_id, [chunk_data])
            chunk_index += 1

        # Save images for this page
        for img in page_result.images:
            if not os.path.exists(img.image_path):
                continue
            database.insert_image(
                doc_id=doc_id,
                page_num=img.page_num,
                image_path=img.image_path,
                image_type="image",
                ocr_text="",
                nearby_text=img.nearby_text,
            )
            image_count += 1

        # Update counts after each page so UI can track progress
        database.update_document_counts(
            doc_id,
            page_count=total_pages,
            image_count=image_count,
            chunk_count=chunk_index,
        )

    database.update_document_status(doc_id, "ready")


def start_processing(doc_id: int, file_path: str, image_output_dir: str):
    """Launch background thread."""
    t = threading.Thread(
        target=process_document,
        args=(doc_id, file_path, image_output_dir),
        daemon=True,
    )
    t.start()
