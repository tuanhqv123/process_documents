import type { Chunk, DocImage, Document, Workspace, Formula } from "@/types"

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
}
