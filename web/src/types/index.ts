export interface Document {
  id: number
  filename: string
  file_path: string
  file_size: number
  page_count: number
  image_count: number
  chunk_count: number
  formula_count: number
  status: "uploaded" | "extracting" | "extracted" | "ready" | "error" | "pending" | "processing"
  error: string | null
  created_at: string
  // OCR pipeline fields
  extract_progress: number
  extract_message: string | null
  extracted_pages: number
  total_pages_ocr: number
  ocr_data_path: string | null
}

export interface OcrLayoutBox {
  bbox: [number, number, number, number]
  category: string
  text?: string
}

export interface OcrPageData {
  page: number
  layout_json: OcrLayoutBox[]
  markdown: string
  image_width: number
  image_height: number
}

export interface ApiKey {
  id: number
  label: string
  type: "ocr" | "llm"
  model_name: string
  is_active: boolean
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

export interface GraphNode {
  id: number
  category: string
  text: string
  page_num: number
  depth: number
  rank: number
  path: string
  bbox: number[] | null
  children: GraphNode[]
}

export interface SearchResult {
  id: number
  doc_id: number
  filename: string
  text: string
  context: string
  category: string
  page_num: number
  bbox: number[]
  score: number
}

export interface RagResult {
  id: number
  doc_id: number
  filename: string
  text: string
  context: string
  category: string
  page_num: number
  bbox: number[]
  score: number
}

export interface TranscriptLine {
  id: number
  device_id: string
  text: string
  timestamp: string   // ISO — maps to SessionTranscript.created_at
}

export interface SessionRagBlock {
  id: number
  session_id: number
  block_start: string   // ISO
  block_end: string     // ISO
  combined_text: string
  rag_results: RagResult[]
  transcripts: TranscriptLine[]
}

export interface RecordingSession {
  id: number
  name: string
  workspace_id: number | null
  workspace_name: string | null
  status: "idle" | "active" | "stopped"
  created_at: string
  started_at: string | null
  ended_at: string | null
  summary: string | null
  block_count: number
  transcript_count: number
}
