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
