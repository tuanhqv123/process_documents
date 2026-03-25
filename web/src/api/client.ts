import type { Chunk, DocImage, Document, Workspace } from "@/types"

const BASE = "http://localhost:8000"

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
    // Convert absolute path to static URL
    // e.g. "data/images/doc_1/page5_img0.jpeg" → "/static/images/doc_1/page5_img0.jpeg"
    const match = imagePath.match(/data\/images\/(.+)/)
    if (match) return `${BASE}/static/images/${match[1]}`
    const filename = imagePath.split("/").pop()
    return `${BASE}/static/images/${filename}`
  },
}
