"""
PDF processing pipeline — 100% RapidDoc

- RapidDoc: Complete document processing (OCR, layout, tables, formulas)
- No custom processing logic, only RapidDoc API
- Yields one page at a time so caller can save incrementally
"""

import os
import time
import base64
from dataclasses import dataclass
from typing import Generator
from pathlib import Path

import pytesseract
from PIL import Image
from pypdfium2 import PdfDocument
from rapid_doc.backend.pipeline.pipeline_analyze import doc_analyze
from rapid_doc.backend.pipeline.model_json_to_middle_json import result_to_middle_json
from rapid_doc.backend.pipeline.pipeline_middle_json_mkcontent import union_make


@dataclass
class PageResult:
    page_num: int
    markdown: str  # Direct markdown from RapidDoc
    html: str  # HTML format (tables, etc.)
    latex_formulas: list[str]  # LaTeX formulas
    images: list[dict]  # Extracted images
    time_sec: float


@dataclass
class PipelineConfig:
    image_output_dir: str = "data/images"


class ImageWriter:
    """Real image writer that saves images to disk."""
    
    def __init__(self, output_dir: str, doc_id: int):
        self.output_dir = Path(output_dir) / str(doc_id)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.image_count = 0
    
    def write(self, img_hash256_path: str, img_bytes: bytes):
        """Write image to disk and return the path."""
        img_hash = img_hash256_path.split('/')[-1].split('.')[0]
        image_filename = f"{img_hash}.png"
        image_path = self.output_dir / image_filename
        
        with open(image_path, 'wb') as f:
            f.write(img_bytes)
        
        self.image_count += 1
        return str(image_path)
    
    def write_image(self, image, image_id: str):
        """Write image from RapidDoc format."""
        if image is None:
            return None
        
        image_filename = f"image_{self.image_count:04d}.png"
        image_path = self.output_dir / image_filename
        
        # Handle bytes or base64
        if isinstance(image, bytes):
            img_bytes = image
        elif isinstance(image, str):
            # Assume base64
            img_bytes = base64.b64decode(image)
        else:
            return None
        
        with open(image_path, 'wb') as f:
            f.write(img_bytes)
        
        self.image_count += 1
        return str(image_path)


class PDFPipeline:

    def __init__(self, file_path: str, config: PipelineConfig | None = None):
        self.file_path = str(file_path)
        self.config = config or PipelineConfig()
        self._rapid_doc_full_result = None
        self._full_markdown = None
        self._middle_json = None
        self._image_writer = None
    
    def page_count(self) -> int:
        doc = PdfDocument(self.file_path)
        count = len(doc)
        doc.close()
        return count
    
    def process_pages(self, doc_id: int) -> Generator[PageResult, None, None]:
        """
        Yield one PageResult at a time with RapidDoc markdown, HTML, formulas, and images.
        Uses RapidDoc's complete pipeline: doc_analyze -> result_to_middle_json -> union_make
        """
        # Process document with RapidDoc once
        if self._rapid_doc_full_result is None:
            print("  [RapidDoc] Processing entire document...")
            t0 = time.time()
            
            # Set environment variable to disable multiprocessing
            os.environ['MINERU_PDF_CONCURRENCY_ENABLED'] = 'false'
            
            # Read PDF as bytes
            with open(self.file_path, 'rb') as f:
                pdf_bytes = f.read()
            
            # Initialize image writer
            self._image_writer = ImageWriter(self.config.image_output_dir, doc_id)
            
            # Run RapidDoc doc_analyze (enable formula extraction)
            self._rapid_doc_full_result = doc_analyze(
                pdf_bytes_list=[pdf_bytes],
                parse_method='auto',
                formula_enable=True,  # Enable formulas
                table_enable=True,
            )
            
            elapsed = time.time() - t0
            print(f"  [RapidDoc] Document processed in {elapsed:.2f}s")
        
        # RapidDoc returns tuple: (infer_results, all_image_lists, all_pdf_docs, lang_list, ocr_enabled_list)
        infer_results = self._rapid_doc_full_result[0]
        all_image_lists = self._rapid_doc_full_result[1]
        all_pdf_docs = self._rapid_doc_full_result[2]
        lang_list = self._rapid_doc_full_result[3]
        ocr_enabled_list = self._rapid_doc_full_result[4]
        
        # Convert to middle JSON format (required by union_make)
        if self._middle_json is None:
            print("  [RapidDoc] Converting to middle JSON format...")
            
            # Convert model results to middle JSON (this extracts and saves images)
            middle_json = result_to_middle_json(
                model_list=infer_results[0],  # First PDF's results
                images_list=all_image_lists[0],  # First PDF's images
                page_dict_list=all_pdf_docs[0],  # First PDF's pages
                image_writer=self._image_writer,  # Real image writer
                lang=lang_list[0],
                ocr_enable=ocr_enabled_list[0],
                formula_enabled=True,  # Enable formulas
                ocr_config=None,
                image_config=None,
            )
            
            self._middle_json = middle_json
            
            # Extract pdf_info from middle JSON
            pdf_info = middle_json.get('pdf_info', [])
            
            print(f"  [RapidDoc] Converting to markdown...")
            # Generate markdown using union_make
            markdown_result = union_make(
                pdf_info_dict=pdf_info,
                make_mode='mm_markdown',
            )
            
            # union_make returns a single markdown string for all pages
            self._full_markdown = markdown_result if isinstance(markdown_result, str) else '\n\n'.join(markdown_result)
            print(f"  [RapidDoc] Markdown generated: {len(self._full_markdown)} chars")
        
        # Split full markdown by pages
        total_pages = len(infer_results[0]) if infer_results else 0
        page_markdowns = self._split_markdown_by_pages(self._full_markdown, total_pages)
        
        # Extract per-page data (HTML, formulas, images)
        pdf_info = self._middle_json.get('pdf_info', [])
        
        for page_num in range(total_pages):
            t0 = time.time()
            
            page_markdown = page_markdowns[page_num] if page_num < len(page_markdowns) else ""
            
            # Extract HTML (tables, etc.) from page markdown
            page_html = self._extract_html_from_markdown(page_markdown)
            
            # Extract formulas from pdf_info
            page_formulas = self._extract_formulas(pdf_info, page_num)
            
            # Extract images from pdf_info
            page_images = self._extract_images(pdf_info, page_num, doc_id)
            
            elapsed = round(time.time() - t0, 2)
            print(f"  [Page {page_num + 1}/{total_pages}] {elapsed}s | Formulas: {len(page_formulas)} | Images: {len(page_images)}")
            
            yield PageResult(
                page_num=page_num,
                markdown=page_markdown,
                html=page_html,
                latex_formulas=page_formulas,
                images=page_images,
                time_sec=elapsed,
            )
    
    def _extract_html_from_markdown(self, markdown: str) -> str:
        """Extract HTML tables from markdown."""
        # Tables in markdown are already in HTML format from RapidDoc
        # Just return the markdown as-is (it contains HTML for tables)
        return markdown
    
    def _extract_formulas(self, pdf_info: list, page_num: int) -> list[str]:
        """Extract LaTeX formulas from pdf_info."""
        formulas = []
        
        if page_num >= len(pdf_info):
            return formulas
        
        page_data = pdf_info[page_num]
        para_blocks = page_data.get('para_blocks', [])
        
        for block in para_blocks:
            # Check if block has formulas
            if block.get('type') == 'display_formula':
                latex = block.get('latex', '')
                if latex:
                    formulas.append(latex)
            elif block.get('type') == 'inline_formula':
                latex = block.get('latex', '')
                if latex:
                    formulas.append(latex)
        
        return formulas
    
    def _extract_images(self, pdf_info: list, page_num: int, doc_id: int) -> list[dict]:
        """Extract images from pdf_info with OCR."""
        images = []
        
        if page_num >= len(pdf_info):
            return images
        
        page_data = pdf_info[page_num]
        para_blocks = page_data.get('para_blocks', [])
        discarded_blocks = page_data.get('discarded_blocks', [])
        all_blocks = para_blocks + discarded_blocks
        
        for block in all_blocks:
            block_images = block.get('images', [])
            for img in block_images:
                image_path = img.get('img_path', '')
                ocr_text = ""
                
                if image_path and os.path.exists(image_path):
                    try:
                        pil_img = Image.open(image_path)
                        ocr_text = pytesseract.image_to_string(pil_img, lang='eng')
                        ocr_text = ocr_text.strip()
                    except Exception as e:
                        print(f"  [OCR] Failed to OCR image {image_path}: {e}")
                
                images.append({
                    'page_num': page_num,
                    'image_id': img.get('img_id', ''),
                    'image_path': image_path,
                    'image_type': img.get('type', 'generic'),
                    'nearby_text': img.get('nearby_text', ''),
                    'ocr_text': ocr_text,
                    'bbox': img.get('bbox', []),
                })
        
        return images
    
    def _split_markdown_by_pages(self, full_markdown: str, total_pages: int) -> list[str]:
        """
        Split full markdown into per-page markdowns.
        union_make returns list of markdown strings, we joined them with "\n\n---\n\n".
        """
        if not full_markdown:
            return [""] * total_pages
        
        # Split by our page delimiter
        pages = full_markdown.split("\n\n---\n\n")
        
        # Ensure we have the correct number of pages
        if len(pages) < total_pages:
            pages += [""] * (total_pages - len(pages))
        elif len(pages) > total_pages:
            pages = pages[:total_pages]
        
        return pages
    
    def get_full_rapid_doc_result(self) -> tuple:
        """Get full RapidDoc result tuple."""
        return self._rapid_doc_full_result
