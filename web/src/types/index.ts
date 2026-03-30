export interface Document {
  id: number
  filename: string
  file_path: string
  file_size: number
  page_count: number
  image_count: number
  chunk_count: number
  formula_count: number
  status: "pending" | "processing" | "ready" | "error"
  error: string | null
  created_at: string
}

export interface Chunk {
  id: number
  doc_id: number
  chunk_index: number
  text: string
  page_start: number
  page_end: number
  section_path: string[]
  element_types: string[]
  is_edited: boolean
}

export interface DocImage {
  id: number
  doc_id: number
  page_num: number
  image_path: string
  image_type: string
  ocr_text: string
  nearby_text: string
  is_edited: boolean
}

export interface Formula {
  id: number
  doc_id: number
  page_num: number
  latex: string
  formula_type: string
  bbox: number[]
  is_edited: boolean
}

export interface Workspace {
  id: number
  name: string
  description: string
  created_at: string
  doc_count: number
}
