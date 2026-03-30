import { useEffect, useState, useCallback, useRef } from "react"
import { FileText, RefreshCw } from "lucide-react"
import { Progress } from "@/components/ui/progress"
import { StatusBadge } from "@/components/status-badge"
import { ChunksPanel } from "@/components/chunks-panel"
import { ImagesPanel } from "@/components/images-panel"
import { FormulasPanel } from "@/components/formulas-panel"
import { api } from "@/api/client"
import type { Chunk, DocImage, Document, Formula } from "@/types"

type ContentItem = 
  | { type: "chunk"; data: Chunk }
  | { type: "image"; data: DocImage }
  | { type: "formula"; data: Formula }

interface DocumentViewProps {
  document: Document
  onDocumentUpdated: (doc: Document) => void
}

export function DocumentView({ document: doc, onDocumentUpdated }: DocumentViewProps) {
  const [chunks, setChunks] = useState<Chunk[]>([])
  const [images, setImages] = useState<DocImage[]>([])
  const [formulas, setFormulas] = useState<Formula[]>([])
  const [contentLoaded, setContentLoaded] = useState(false)
  const onDocumentUpdatedRef = useRef(onDocumentUpdated)
  onDocumentUpdatedRef.current = onDocumentUpdated

  const isProcessing = doc.status === "processing" || doc.status === "pending"
  const progress = doc.page_count > 0 ? Math.round((doc.chunk_count / doc.page_count) * 100) : 0

  // Poll document status while processing using setTimeout (one poll at a time)
  useEffect(() => {
    let cancelled = false
    let timeoutId: number | null = null

    const poll = async () => {
      if (cancelled) return

      const updated = await api.documents.get(doc.id)
      if (cancelled) return

      onDocumentUpdatedRef.current(updated)

      // Schedule next poll if still processing
      if (updated.status === "pending" || updated.status === "processing") {
        timeoutId = window.setTimeout(poll, 3000)
      }
    }

    // Start polling if document is still processing
    if (doc.status === "pending" || doc.status === "processing") {
      timeoutId = window.setTimeout(poll, 3000)
    }

    return () => {
      cancelled = true
      if (timeoutId) {
        clearTimeout(timeoutId)
      }
    }
  }, [doc.id])

  // Load all content once when ready
  useEffect(() => {
    if (doc.status !== "ready" || contentLoaded) return
    
    api.documents.content(doc.id).then((data) => {
      setChunks(data.chunks)
      setImages(data.images)
      setFormulas(data.formulas)
      setContentLoaded(true)
    })
  }, [doc.id, doc.status, contentLoaded])

  const handleChunkUpdated = useCallback((id: number, text: string) => {
    setChunks((prev) =>
      prev.map((c) => (c.id === id ? { ...c, text, is_edited: true } : c))
    )
  }, [])

  const handleImageUpdated = useCallback((id: number, ocr_text: string) => {
    setImages((prev) =>
      prev.map((img) => (img.id === id ? { ...img, ocr_text, is_edited: true } : img))
    )
  }, [])

  const mergedContent: ContentItem[] = []
  const maxPage = Math.max(
    doc.page_count,
    ...chunks.map(c => c.page_end + 1),
    ...images.map(i => i.page_num + 1),
    ...formulas.map(f => f.page_num + 1)
  )

  for (let page = 0; page < maxPage; page++) {
    chunks.filter(c => page >= c.page_start && page <= c.page_end)
      .sort((a, b) => a.chunk_index - b.chunk_index)
      .forEach(chunk => mergedContent.push({ type: "chunk", data: chunk }))
    images.filter(i => i.page_num === page)
      .sort((a, b) => a.id - b.id)
      .forEach(img => mergedContent.push({ type: "image", data: img }))
    formulas.filter(f => f.page_num === page)
      .sort((a, b) => a.bbox[1] - b.bbox[1])
      .forEach(formula => mergedContent.push({ type: "formula", data: formula }))
  }

  const renderContent = () => {
    if (mergedContent.length === 0 && !isProcessing) {
      return (
        <div className="flex items-center justify-center h-40 text-muted-foreground text-sm">
          No content extracted.
        </div>
      )
    }

    return (
      <div className="space-y-6">
        {mergedContent.map((item) => {
          if (item.type === "chunk") {
            return (
              <ChunksPanel 
                key={`chunk-${item.data.id}`} 
                chunks={[item.data]} 
                onChunkUpdated={handleChunkUpdated} 
              />
            )
          }
          if (item.type === "image") {
            return (
              <ImagesPanel 
                key={`image-${item.data.id}`} 
                images={[item.data]} 
                onImageUpdated={handleImageUpdated} 
              />
            )
          }
          if (item.type === "formula") {
            return (
              <FormulasPanel 
                key={`formula-${item.data.id}`} 
                formulas={[item.data]} 
              />
            )
          }
          return null
        })}
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Compact header */}
      <div className="px-6 py-3 border-b shrink-0">
        <div className="flex items-center gap-3">
          <FileText className="h-5 w-5 text-muted-foreground shrink-0" />
          <span className="font-semibold truncate">{doc.filename}</span>
          <StatusBadge status={doc.status} />
          <span className="text-xs text-muted-foreground shrink-0">
            {doc.page_count > 0 && `${doc.page_count}p`}
            {doc.chunk_count > 0 && ` · ${doc.chunk_count} chunks`}
            {doc.image_count > 0 && ` · ${doc.image_count} images`}
            {doc.formula_count > 0 && ` · ${doc.formula_count} formulas`}
          </span>
        </div>
        {doc.error && (
          <p className="text-sm text-destructive mt-1">{doc.error}</p>
        )}
        {/* Progress bar while processing */}
        {isProcessing && doc.page_count > 0 && (
          <div className="flex items-center gap-3 mt-2">
            <Progress value={progress} className="flex-1 h-2" />
            <span className="text-xs text-muted-foreground shrink-0">
              {doc.chunk_count}/{doc.page_count} pages
            </span>
          </div>
        )}
        {isProcessing && doc.page_count === 0 && (
          <div className="flex items-center gap-2 mt-2">
            <RefreshCw className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
            <span className="text-xs text-muted-foreground">Starting…</span>
          </div>
        )}
      </div>

        {/* Content — show all content in one page, sorted by page order */}
        <div className="flex-1 overflow-y-auto p-6">
          {chunks.length === 0 && images.length === 0 && formulas.length === 0 && !isProcessing ? (
            <div className="flex items-center justify-center h-40 text-muted-foreground text-sm">
              No content extracted.
            </div>
          ) : (
            renderContent()
          )}
        </div>
      </div>
    )
  }
