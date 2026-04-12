"""Pydantic request/response models."""

from pydantic import BaseModel
from typing import Optional


class WorkspaceCreate(BaseModel):
    name: str
    description: str = ""


class WorkspaceOut(BaseModel):
    id: int
    name: str
    description: str
    created_at: str
    doc_count: int = 0


class DocumentOut(BaseModel):
    id: int
    filename: str
    file_path: str
    file_size: int
    page_count: int
    image_count: int
    chunk_count: int
    formula_count: int = 0
    status: str
    error: Optional[str]
    created_at: str
    # OCR extraction fields
    extract_progress: int = 0
    extract_message: Optional[str] = None
    extracted_pages: int = 0
    total_pages_ocr: int = 0
    ocr_data_path: Optional[str] = None


class ChunkOut(BaseModel):
    id: int
    doc_id: int
    chunk_index: int
    text: str
    page_start: int
    page_end: int
    section_path: list[str]
    element_types: list[str]
    is_edited: bool


class ChunkUpdate(BaseModel):
    text: str


class ImageOut(BaseModel):
    id: int
    doc_id: int
    page_num: int
    image_path: str
    image_type: str
    ocr_text: str
    nearby_text: str
    is_edited: bool


class ImageUpdate(BaseModel):
    ocr_text: str


class FormulaOut(BaseModel):
    id: int
    doc_id: int
    page_num: int
    latex: str
    formula_type: str
    bbox: list[float]
    is_edited: bool


class AddDocToWorkspace(BaseModel):
    doc_id: int


class ApiKeyCreate(BaseModel):
    label: str
    type: str  # "ocr" | "llm"
    base_url: str
    api_key: str = ""
    model_name: str = ""


class ApiKeyUpdate(BaseModel):
    label: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model_name: Optional[str] = None


class ApiKeyOut(BaseModel):
    id: int
    label: str
    type: str
    # base_url is intentionally hidden from responses
    model_name: str
    is_active: bool
    created_at: str
