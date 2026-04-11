import type { Chunk, DocImage, Document, Workspace, Formula, OcrPageData, ApiKey, SearchResult, RecordingSession, SessionRagBlock } from "@/types"

const BASE = import.meta.env.VITE_API_URL || ""

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(err || `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

// ── Documents ──────────────────────────────────────────────────────────────────

export const api = {
  documents: {
    list: () => request<Document[]>("/api/documents"),
    get: (id: number) => request<Document>(`/api/documents/${id}`),
    upload: (file: File) => {
      const form = new FormData()
      form.append("file", file)
      return fetch(`${BASE}/api/documents/upload`, { method: "POST", body: form }).then(
        (r) => r.json() as Promise<Document>
      )
    },
    delete: (id: number) => request<{ ok: boolean }>(`/api/documents/${id}`, { method: "DELETE" }),
    chunks: (id: number) => request<Chunk[]>(`/api/documents/${id}/chunks`),
    images: (id: number) => request<DocImage[]>(`/api/documents/${id}/images`),
    formulas: (id: number) => request<Formula[]>(`/api/documents/${id}/formulas`),
    content: (id: number) => request<{ document: Document; chunks: Chunk[]; images: DocImage[]; formulas: Formula[] }>(`/api/documents/${id}/content`),
    workspaces: (id: number) => request<{ id: number; name: string }[]>(`/api/documents/${id}/workspaces`),
  },

  chunks: {
    update: (id: number, text: string) =>
      request<{ ok: boolean }>(`/api/chunks/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ text }),
      }),
  },

  images: {
    update: (id: number, ocr_text: string) =>
      request<{ ok: boolean }>(`/api/images/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ ocr_text }),
      }),
  },

  workspaces: {
    list: () => request<Workspace[]>("/api/workspaces"),
    create: (name: string, description = "") =>
      request<Workspace>("/api/workspaces", {
        method: "POST",
        body: JSON.stringify({ name, description }),
      }),
    delete: (id: number) =>
      request<{ ok: boolean }>(`/api/workspaces/${id}`, { method: "DELETE" }),
    documents: (id: number) => request<Document[]>(`/api/workspaces/${id}/documents`),
    addDocument: (wsId: number, docId: number) =>
      request<{ ok: boolean }>(`/api/workspaces/${wsId}/documents`, {
        method: "POST",
        body: JSON.stringify({ doc_id: docId }),
      }),
    removeDocument: (wsId: number, docId: number) =>
      request<{ ok: boolean }>(`/api/workspaces/${wsId}/documents/${docId}`, {
        method: "DELETE",
      }),
    search: (wsId: number, query: string, topK = 8, minScore = 0.0) =>
      request<SearchResult[]>(`/api/workspaces/${wsId}/search`, {
        method: "POST",
        body: JSON.stringify({ query, top_k: topK, min_score: minScore }),
      }),
  },

  // ── Extract / Train / OCR ──────────────────────────────────────────────────
  extract: {
    start: (id: number) => request<Document>(`/api/documents/${id}/extract`, { method: "POST" }),
    cancel: (id: number) => request<{ ok: boolean }>(`/api/documents/${id}/extract-cancel`, { method: "POST" }),
    status: (id: number) => request<Document>(`/api/documents/${id}/extract-status`),
    train: (id: number) => request<Document>(`/api/documents/${id}/train`, { method: "POST" }),
    ocrPages: (id: number) => request<{ doc_id: number; total_pages: number; pages: OcrPageData[] }>(`/api/documents/${id}/ocr-pages`),
    pageImageUrl: (id: number, pageNum: number) => `${BASE}/api/documents/${id}/page-image/${pageNum}`,
    extractPage: (id: number, page_num: number) =>
      request<{ ok: boolean; page: number; page_data: OcrPageData }>(`/api/documents/${id}/extract-page?page_num=${page_num}`, { method: "POST" }),
    updateOcrBlock: (id: number, page_num: number, block_idx: number, text: string) =>
      request<{ ok: boolean }>(`/api/documents/${id}/ocr-block`, {
        method: "PATCH",
        body: JSON.stringify({ page_num, block_idx, text }),
      }),
    graph: (id: number) => request<{ doc_id: number; total_nodes: number; leaf_nodes: number; tree: GraphNode }>(`/api/documents/${id}/graph`),
  },

  // ── API Keys / Model Config ───────────────────────────────────────────────────
  apiKeys: {
    list: () => request<ApiKey[]>("/api/api-keys/"),
    create: (data: { label: string; type: string; base_url: string; api_key?: string; model_name?: string }) =>
      request<ApiKey>("/api/api-keys/", { method: "POST", body: JSON.stringify(data) }),
    update: (id: number, data: { label?: string; base_url?: string; api_key?: string; model_name?: string }) =>
      request<ApiKey>(`/api/api-keys/${id}`, { method: "PUT", body: JSON.stringify(data) }),
    delete: (id: number) => request<{ ok: boolean }>(`/api/api-keys/${id}`, { method: "DELETE" }),
    activate: (id: number) => request<{ ok: boolean }>(`/api/api-keys/${id}/activate`, { method: "POST" }),
    test: (id: number) =>
      request<{ ok: boolean; latency_ms: number; models: string[]; error: string | null }>(
        `/api/api-keys/${id}/test`, { method: "POST" }
      ),
    testConnection: (base_url: string, api_key?: string) =>
      request<{ ok: boolean; latency_ms: number; models: string[]; error: string | null }>(
        "/api/api-keys/test-connection",
        { method: "POST", body: JSON.stringify({ base_url, api_key }) }
      ),
  },

  imageUrl: (imagePath: string) => {
    const match = imagePath.match(/data\/images\/(.+)/)
    if (match) return `${BASE}/static/images/${match[1]}`
    const filename = imagePath.split("/").pop()
    return `${BASE}/static/images/${filename}`
  },

  realtime: {
    getAudio: (deviceId: string, limit = 100) =>
      request<{ time: string; device_id: string; amplitude: number; peak: number }[]>(
        `/api/realtime/audio/${deviceId}?limit=${limit}`
      ),
    getTranscripts: (limit = 50) =>
      request<{ time: string; device_id: string; text: string }[]>(
        `/api/realtime/transcripts?limit=${limit}`
      ),
    postAudio: (deviceId: string, amplitude: number, peak = 0) =>
      request<{ status: string }>("/api/realtime/audio", {
        method: "POST",
        body: JSON.stringify({ device_id: deviceId, amplitude, peak }),
      }),
    postTranscript: (deviceId: string, text: string) =>
      request<{ status: string }>("/api/realtime/transcript", {
        method: "POST",
        body: JSON.stringify({ device_id: deviceId, text }),
      }),
    transcribeAudio: async (deviceId: string, file: File) => {
      const form = new FormData()
      form.append("file", file)
      const res = await fetch(`${BASE}/api/realtime/transcribe?device_id=${deviceId}`, {
        method: "POST",
        body: form,
      })
      return res.json() as Promise<{ text: string }>
    },
  },

  sessions: {
    list: () => request<RecordingSession[]>("/api/sessions"),
    create: (name: string, workspace_id: number | null) =>
      request<RecordingSession>("/api/sessions", {
        method: "POST",
        body: JSON.stringify({ name, workspace_id }),
      }),
    get: (id: number) => request<RecordingSession>(`/api/sessions/${id}`),
    delete: (id: number) =>
      request<{ ok: boolean }>(`/api/sessions/${id}`, { method: "DELETE" }),
    start: (id: number) =>
      request<RecordingSession>(`/api/sessions/${id}/start`, { method: "POST" }),
    stop: (id: number) =>
      request<RecordingSession>(`/api/sessions/${id}/stop`, { method: "POST" }),
    blocks: (id: number, after?: string) =>
      request<SessionRagBlock[]>(
        `/api/sessions/${id}/blocks${after ? `?after=${encodeURIComponent(after)}` : ""}`
      ),
    summarize: (id: number) =>
      request<RecordingSession>(`/api/sessions/${id}/summarize`, { method: "POST" }),
  },
}
