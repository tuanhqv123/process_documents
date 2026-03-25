import { useState } from "react"
import { Pencil, Check, X, ChevronRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { api } from "@/api/client"
import type { Chunk } from "@/types"

interface ChunksPanelProps {
  chunks: Chunk[]
  onChunkUpdated: (id: number, text: string) => void
}

export function ChunksPanel({ chunks, onChunkUpdated }: ChunksPanelProps) {
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editText, setEditText] = useState("")
  const [saving, setSaving] = useState(false)

  const startEdit = (chunk: Chunk) => {
    setEditingId(chunk.id)
    setEditText(chunk.text)
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditText("")
  }

  const saveEdit = async (id: number) => {
    setSaving(true)
    try {
      await api.chunks.update(id, editText)
      onChunkUpdated(id, editText)
      setEditingId(null)
    } finally {
      setSaving(false)
    }
  }

  if (chunks.length === 0) {
    return (
      <div className="flex items-center justify-center h-40 text-muted-foreground text-sm">
        No chunks yet — document may still be processing.
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {chunks.map((chunk) => (
          <div
            key={chunk.id}
            className="border rounded-lg p-4 space-y-2 hover:border-primary/40 transition-colors"
          >
            {/* Header */}
            <div className="flex items-start justify-between gap-2">
              <div className="flex flex-wrap items-center gap-1.5 min-w-0">
                {chunk.section_path.length > 0 && (
                  <div className="flex items-center gap-1 text-xs text-muted-foreground font-medium">
                    {chunk.section_path.map((s, i) => (
                      <span key={i} className="flex items-center gap-1">
                        {i > 0 && <ChevronRight className="h-3 w-3" />}
                        <span className="truncate max-w-[120px]">{s}</span>
                      </span>
                    ))}
                  </div>
                )}
                <span className="text-xs text-muted-foreground">
                  p.{chunk.page_start + 1}
                  {chunk.page_end !== chunk.page_start ? `–${chunk.page_end + 1}` : ""}
                </span>
                {chunk.is_edited && (
                  <Badge variant="outline" className="text-xs h-4 px-1">edited</Badge>
                )}
              </div>
              {editingId !== chunk.id && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 w-7 p-0 shrink-0"
                  onClick={() => startEdit(chunk)}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
              )}
            </div>

            {/* Content */}
            {editingId === chunk.id ? (
              <div className="space-y-2">
                <Textarea
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                  rows={8}
                  className="text-sm font-mono"
                />
                <div className="flex gap-2 justify-end">
                  <Button variant="outline" size="sm" onClick={cancelEdit} disabled={saving}>
                    <X className="h-3.5 w-3.5 mr-1" />
                    Cancel
                  </Button>
                  <Button size="sm" onClick={() => saveEdit(chunk.id)} disabled={saving}>
                    <Check className="h-3.5 w-3.5 mr-1" />
                    {saving ? "Saving…" : "Save"}
                  </Button>
                </div>
              </div>
            ) : (
              <p className="text-sm leading-relaxed whitespace-pre-wrap">
                {chunk.text}
              </p>
            )}
          </div>
        ))}
    </div>
  )
}
