import { useState } from "react"
import { Pencil, Check, X, Image as ImageIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { api } from "@/api/client"
import type { DocImage } from "@/types"

interface ImagesPanelProps {
  images: DocImage[]
  onImageUpdated: (id: number, ocr_text: string) => void
}

function isHtmlTable(text: string): boolean {
  return text.trimStart().startsWith("<table")
}

const IMAGE_TYPE_COLORS: Record<string, string> = {
  table: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
  chart: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300",
  formula: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300",
  flowchart: "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300",
  state_diagram: "bg-pink-100 text-pink-700 dark:bg-pink-900/30 dark:text-pink-300",
  generic: "bg-muted text-muted-foreground",
}

export function ImagesPanel({ images, onImageUpdated }: ImagesPanelProps) {
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editText, setEditText] = useState("")
  const [saving, setSaving] = useState(false)
  const [imgErrors, setImgErrors] = useState<Set<number>>(new Set())

  const startEdit = (img: DocImage) => {
    setEditingId(img.id)
    setEditText(img.ocr_text)
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditText("")
  }

  const saveEdit = async (id: number) => {
    setSaving(true)
    try {
      await api.images.update(id, editText)
      onImageUpdated(id, editText)
      setEditingId(null)
    } finally {
      setSaving(false)
    }
  }

  if (images.length === 0) {
    return (
      <div className="flex items-center justify-center h-40 text-muted-foreground text-sm">
        No images found in this document.
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {images.map((img) => {
          const imgUrl = api.imageUrl(img.image_path)
          const typeColor = IMAGE_TYPE_COLORS[img.image_type] ?? IMAGE_TYPE_COLORS.generic

          return (
            <div
              key={img.id}
              className="border rounded-lg overflow-hidden hover:border-primary/40 transition-colors"
            >
              {/* Image */}
              <div className="relative bg-muted aspect-video flex items-center justify-center overflow-hidden">
                {imgErrors.has(img.id) ? (
                  <div className="flex flex-col items-center gap-1 text-muted-foreground">
                    <ImageIcon className="h-8 w-8" />
                    <span className="text-xs">Image not available</span>
                  </div>
                ) : (
                  <img
                    src={imgUrl}
                    alt={`Page ${img.page_num + 1} image`}
                    className="max-h-full max-w-full object-contain"
                    onError={() => setImgErrors((prev) => new Set(prev).add(img.id))}
                  />
                )}
              </div>

              {/* Meta */}
              <div className="p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className={`text-xs font-medium px-2 py-0.5 rounded-full ${typeColor}`}
                    >
                      {img.image_type}
                    </span>
                    <span className="text-xs text-muted-foreground">page {img.page_num + 1}</span>
                    {img.is_edited && (
                      <Badge variant="outline" className="text-xs h-4 px-1">edited</Badge>
                    )}
                  </div>
                  {editingId !== img.id && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 w-7 p-0"
                      onClick={() => startEdit(img)}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>

                {/* OCR text */}
                {editingId === img.id ? (
                  <div className="space-y-2">
                    <Textarea
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      rows={5}
                      className="text-xs font-mono"
                      placeholder="OCR content..."
                    />
                    <div className="flex gap-2 justify-end">
                      <Button variant="outline" size="sm" onClick={cancelEdit} disabled={saving}>
                        <X className="h-3.5 w-3.5 mr-1" />
                        Cancel
                      </Button>
                      <Button size="sm" onClick={() => saveEdit(img.id)} disabled={saving}>
                        <Check className="h-3.5 w-3.5 mr-1" />
                        {saving ? "Saving…" : "Save"}
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div>
                    {img.ocr_text ? (
                      isHtmlTable(img.ocr_text) ? (
                        <div
                          className="text-xs leading-relaxed overflow-x-auto [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-border [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-border [&_th]:px-2 [&_th]:py-1 [&_th]:bg-muted [&_th]:font-medium"
                          dangerouslySetInnerHTML={{ __html: img.ocr_text }}
                        />
                      ) : (
                        <p className="text-xs whitespace-pre-wrap font-mono leading-relaxed">
                          {img.ocr_text}
                        </p>
                      )
                    ) : (
                      <p className="text-xs text-muted-foreground italic">No OCR content</p>
                    )}
                    {img.nearby_text && (
                      <p className="text-xs text-muted-foreground/60 mt-1">
                        Context: {img.nearby_text}
                      </p>
                    )}
                  </div>
                )}
              </div>
            </div>
          )
        })}
    </div>
  )
}
