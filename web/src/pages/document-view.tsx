import { useEffect, useState, useCallback } from "react"
import { FileText, Layers, Image, RefreshCw } from "lucide-react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Progress } from "@/components/ui/progress"
import { StatusBadge } from "@/components/status-badge"
import { ChunksPanel } from "@/components/chunks-panel"
import { ImagesPanel } from "@/components/images-panel"
import { api } from "@/api/client"
import type { Chunk, DocImage, Document } from "@/types"

interface DocumentViewProps {
  document: Document
  onDocumentUpdated: (doc: Document) => void
}

export function DocumentView({ document: doc, onDocumentUpdated }: DocumentViewProps) {
  const [chunks, setChunks] = useState<Chunk[]>([])
  const [images, setImages] = useState<DocImage[]>([])
  const [loading, setLoading] = useState(false)

  const isProcessing = doc.status === "processing" || doc.status === "pending"
  const progress = doc.page_count > 0 ? Math.round((doc.chunk_count / doc.page_count) * 100) : 0

  // Poll while processing — also fetch live chunks/images
  useEffect(() => {
    if (!isProcessing) return

    const poll = async () => {
      const updated = await api.documents.get(doc.id)
      onDocumentUpdated(updated)

      // Fetch chunks/images that have been saved so far
      const [c, i] = await Promise.all([
        api.documents.chunks(doc.id),
        api.documents.images(doc.id),
      ])
      setChunks(c)
      setImages(i)

      if (updated.status === "ready" || updated.status === "error") {
        clearInterval(timer)
      }
    }

    const timer = setInterval(poll, 2000)
    poll() // initial fetch
    return () => clearInterval(timer)
  }, [doc.id, isProcessing])

  // Load content when ready (final load)
  useEffect(() => {
    if (doc.status !== "ready") return
    setLoading(true)
    Promise.all([api.documents.chunks(doc.id), api.documents.images(doc.id)])
      .then(([c, i]) => {
        setChunks(c)
        setImages(i)
      })
      .finally(() => setLoading(false))
  }, [doc.id, doc.status])

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

      {/* Content — show tabs even while processing so chunks appear live */}
      {loading && !isProcessing ? (
        <div className="flex items-center justify-center flex-1 text-muted-foreground text-sm">
          Loading content…
        </div>
      ) : (
        <Tabs defaultValue="chunks" className="flex-1 flex flex-col min-h-0">
          <TabsList className="w-full rounded-none border-b bg-transparent h-10 px-6">
            <TabsTrigger value="chunks" className="gap-1.5 data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none">
              <Layers className="h-3.5 w-3.5" />
              Pages
              {chunks.length > 0 && (
                <span className="ml-1 text-xs text-muted-foreground">({chunks.length})</span>
              )}
            </TabsTrigger>
            <TabsTrigger value="images" className="gap-1.5 data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none">
              <Image className="h-3.5 w-3.5" />
              Images
              {images.length > 0 && (
                <span className="ml-1 text-xs text-muted-foreground">({images.length})</span>
              )}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="chunks" className="flex-1 overflow-y-auto mt-0 p-6">
            {chunks.length === 0 && !isProcessing ? (
              <div className="flex items-center justify-center h-40 text-muted-foreground text-sm">
                No content extracted.
              </div>
            ) : (
              <ChunksPanel chunks={chunks} onChunkUpdated={handleChunkUpdated} />
            )}
          </TabsContent>
          <TabsContent value="images" className="flex-1 overflow-y-auto mt-0 p-6">
            <ImagesPanel images={images} onImageUpdated={handleImageUpdated} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  )
}
