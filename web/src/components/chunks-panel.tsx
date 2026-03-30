import { useState } from "react"
import ReactMarkdown from "react-markdown"
import rehypeRaw from "rehype-raw"
import remarkMath from "remark-math"
import rehypeKatex from "rehype-katex"
import katex from "katex"
import type { Components } from "react-markdown"
import type { ReactNode } from "react"
import "katex/dist/katex.min.css"
import { Pencil, Check, X, ChevronRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table"
import { api } from "@/api/client"
import type { Chunk } from "@/types"

function containsHtmlTable(text: string): boolean {
  return /<table[\s>]/i.test(text)
}

function containsLatex(text: string): boolean {
  return /\$[^$]+\$|\$\$[^$]+\$\$|\\\[.*?\\\]|\\\(.*?\\\)/.test(text)
}

const LATEX_INLINE = /(\$[^$]+\$)/g

function renderLatexText(text: string): ReactNode[] {
  const parts = text.split(LATEX_INLINE)
  return parts.map((part, i) => {
    if (part.startsWith("$") && part.endsWith("$") && part.length > 2) {
      const latex = part.slice(1, -1)
      try {
        const html = katex.renderToString(latex, { throwOnError: false })
        return <span key={i} dangerouslySetInnerHTML={{ __html: html }} />
      } catch {
        return <span key={i}>{part}</span>
      }
    }
    return <span key={i}>{part}</span>
  })
}

function renderChildrenWithLatex(children: ReactNode): ReactNode {
  if (typeof children === "string") {
    if (LATEX_INLINE.test(children)) {
      return renderLatexText(children)
    }
    return children
  }
  return children
}

const markdownComponents: Components = {
  table({ children, ...props }) {
    return <Table {...props}>{children}</Table>
  },
  thead({ children, ...props }) {
    return <TableHeader {...props}>{children}</TableHeader>
  },
  tbody({ children, ...props }) {
    return <TableBody {...props}>{children}</TableBody>
  },
  tr({ children, ...props }) {
    return <TableRow {...props}>{children}</TableRow>
  },
  th({ children, ...props }) {
    return <TableHead className="bg-muted font-semibold" {...props}>{renderChildrenWithLatex(children)}</TableHead>
  },
  td({ children, ...props }) {
    return <TableCell {...props}>{renderChildrenWithLatex(children)}</TableCell>
  },
}

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
            ) : containsHtmlTable(chunk.text) || containsLatex(chunk.text) ? (
              <div className="text-sm leading-relaxed">
                <ReactMarkdown
                  rehypePlugins={[rehypeRaw, rehypeKatex]}
                  remarkPlugins={[remarkMath]}
                  components={markdownComponents}
                >
                  {chunk.text}
                </ReactMarkdown>
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
