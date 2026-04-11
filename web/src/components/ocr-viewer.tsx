import { useState, useRef, useEffect, useCallback } from "react"
import {
  ChevronLeft, ChevronRight, ZoomIn, ZoomOut, RotateCcw,
  Eye, EyeOff, Loader2, Pencil, Check, X,
} from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkMath from "remark-math"
import rehypeKatex from "rehype-katex"
import rehypeRaw from "rehype-raw"
import "katex/dist/katex.min.css"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import type { OcrPageData } from "@/types"
import { api } from "@/api/client"

// ── Colors ────────────────────────────────────────────────────────────────────

const CATEGORY_COLORS: Record<string, { bg: string; border: string; label: string; badge: string }> = {
  Title:            { bg: "rgba(239,68,68,0.12)",  border: "rgba(239,68,68,0.5)",  label: "#ef4444", badge: "bg-red-100 text-red-700" },
  "Section-header": { bg: "rgba(249,115,22,0.12)", border: "rgba(249,115,22,0.5)", label: "#f97316", badge: "bg-orange-100 text-orange-700" },
  Text:             { bg: "rgba(59,130,246,0.10)",  border: "rgba(59,130,246,0.4)", label: "#3b82f6", badge: "bg-blue-100 text-blue-700" },
  "List-item":      { bg: "rgba(16,185,129,0.10)",  border: "rgba(16,185,129,0.4)", label: "#10b981", badge: "bg-emerald-100 text-emerald-700" },
  Table:            { bg: "rgba(168,85,247,0.12)",  border: "rgba(168,85,247,0.5)", label: "#a855f7", badge: "bg-purple-100 text-purple-700" },
  Figure:           { bg: "rgba(236,72,153,0.12)",  border: "rgba(236,72,153,0.5)", label: "#ec4899", badge: "bg-pink-100 text-pink-700" },
  Picture:          { bg: "rgba(236,72,153,0.12)",  border: "rgba(236,72,153,0.5)", label: "#ec4899", badge: "bg-pink-100 text-pink-700" },
  Formula:          { bg: "rgba(45,212,191,0.12)",  border: "rgba(45,212,191,0.5)", label: "#2dd4bf", badge: "bg-teal-100 text-teal-700" },
  Caption:          { bg: "rgba(245,158,11,0.12)",  border: "rgba(245,158,11,0.5)", label: "#f59e0b", badge: "bg-yellow-100 text-yellow-700" },
  "Page-header":    { bg: "rgba(99,102,241,0.10)",  border: "rgba(99,102,241,0.4)", label: "#6366f1", badge: "bg-indigo-100 text-indigo-700" },
  "Page-footer":    { bg: "rgba(107,114,128,0.10)", border: "rgba(107,114,128,0.4)",label: "#6b7280", badge: "bg-gray-100 text-gray-600" },
  Footnote:         { bg: "rgba(78,205,196,0.10)",  border: "rgba(78,205,196,0.4)", label: "#4ecdc4", badge: "bg-cyan-100 text-cyan-700" },
  default:          { bg: "rgba(107,114,128,0.08)", border: "rgba(107,114,128,0.3)",label: "#6b7280", badge: "bg-gray-100 text-gray-600" },
}

function getColor(cat: string) {
  return CATEGORY_COLORS[cat] ?? CATEGORY_COLORS.default
}

// Visual indent level by category rank (mirrors document_nodes hierarchy)
const CATEGORY_INDENT: Record<string, number> = {
  Title: 0,
  "Section-header": 1,
}
function getIndent(cat: string): number {
  if (cat in CATEGORY_INDENT) return CATEGORY_INDENT[cat]
  return 2 // leaf nodes: Text, List-item, Table, Figure, Picture, Formula, etc.
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface OcrViewerProps {
  docId: number
  pages: OcrPageData[]
  totalPages: number
  currentPage?: number
  onPageChange?: (page: number) => void
  onPagesUpdated?: (pages: OcrPageData[]) => void
}

// ── Component ─────────────────────────────────────────────────────────────────

export function OcrViewer({ docId, pages: initialPages, totalPages, currentPage: controlledPage, onPageChange, onPagesUpdated }: OcrViewerProps) {
  const total = totalPages || initialPages.length
  const [pages, setPages] = useState<OcrPageData[]>(initialPages)
  const [currentPage, setCurrentPageLocal] = useState(controlledPage ?? 1)

  const setCurrentPage = useCallback((p: number | ((prev: number) => number)) => {
    setCurrentPageLocal((prev) => {
      const next = typeof p === "function" ? p(prev) : p
      onPageChange?.(next)
      return next
    })
  }, [onPageChange])
  const [zoom, setZoom] = useState(1)
  const [showBoxes, setShowBoxes] = useState(true)
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null)
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null)
  const [pageImage, setPageImage] = useState<string | null>(null)
  const [loadingPage, setLoadingPage] = useState(false)
  const [imgNatural, setImgNatural] = useState({ w: 0, h: 0 })

  // Edit
  const [editingIdx, setEditingIdx] = useState<number | null>(null)
  const [editText, setEditText] = useState("")
  const [saving, setSaving] = useState(false)

  const imgRef = useRef<HTMLImageElement>(null)
  const blockRefs = useRef<Record<number, HTMLDivElement | null>>({})

  useEffect(() => { setPages(initialPages) }, [initialPages])

  const page = pages.find((p) => p.page === currentPage) ?? null
  const blocks = page?.layout_json ?? []
  const pageW = imgNatural.w || 1
  const pageH = imgNatural.h || 1

  // Load page image
  useEffect(() => {
    if (!docId) return
    let cancelled = false
    setLoadingPage(true)
    setPageImage(null)
    setSelectedIdx(null)
    setEditingIdx(null)

    fetch(api.extract.pageImageUrl(docId, currentPage))
      .then((res) => {
        if (!res.ok) throw new Error("Failed")
        const w = parseInt(res.headers.get("X-Image-Width") ?? "0", 10)
        const h = parseInt(res.headers.get("X-Image-Height") ?? "0", 10)
        if (w && h && !cancelled) setImgNatural({ w, h })
        return res.blob()
      })
      .then((blob) => { if (!cancelled) setPageImage(URL.createObjectURL(blob)) })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoadingPage(false) })

    return () => { cancelled = true }
  }, [docId, currentPage])

  // Scroll right panel to selected block
  useEffect(() => {
    if (selectedIdx !== null) {
      blockRefs.current[selectedIdx]?.scrollIntoView({ block: "nearest", behavior: "smooth" })
    }
  }, [selectedIdx])

  // Edit handlers
  const startEdit = (idx: number, text: string) => {
    setEditingIdx(idx)
    setEditText(text)
  }

  const cancelEdit = () => { setEditingIdx(null); setEditText("") }

  const saveEdit = async (idx: number) => {
    setSaving(true)
    try {
      await api.extract.updateOcrBlock(docId, currentPage, idx, editText)
      const updated = pages.map((p) => {
        if (p.page !== currentPage) return p
        return { ...p, layout_json: p.layout_json.map((b, i) => i === idx ? { ...b, text: editText } : b) }
      })
      setPages(updated)
      onPagesUpdated?.(updated)
      setEditingIdx(null)
    } catch (e) {
      alert("Save failed: " + (e instanceof Error ? e.message : e))
    } finally {
      setSaving(false)
    }
  }

  const activeCategories = [...new Set(blocks.map((b) => b.category))]

  return (
    <div className="flex w-full border">

      {/* ── LEFT: image + bounding boxes — 50% ───────────────────────────── */}
      <div className="w-1/2 flex flex-col border-r">

        {/* Toolbar */}
        <div className="flex items-center justify-between px-3 py-2 bg-muted/40 border-b shrink-0">
          <div className="flex items-center gap-1">
            <button
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              disabled={currentPage <= 1}
              className="p-1.5 rounded hover:bg-muted disabled:opacity-30 text-muted-foreground"
            >
              <ChevronLeft size={15} />
            </button>
            <span className="text-xs text-muted-foreground min-w-[76px] text-center">
              Page {currentPage} / {total}
            </span>
            <button
              onClick={() => setCurrentPage((p) => Math.min(total, p + 1))}
              disabled={currentPage >= total}
              className="p-1.5 rounded hover:bg-muted disabled:opacity-30 text-muted-foreground"
            >
              <ChevronRight size={15} />
            </button>
          </div>

          <div className="flex items-center gap-1">
            <button onClick={() => setZoom((z) => Math.max(0.25, z - 0.25))} className="p-1.5 rounded hover:bg-muted text-muted-foreground"><ZoomOut size={13} /></button>
            <span className="text-[11px] text-muted-foreground min-w-[36px] text-center">{Math.round(zoom * 100)}%</span>
            <button onClick={() => setZoom((z) => Math.min(3, z + 0.25))} className="p-1.5 rounded hover:bg-muted text-muted-foreground"><ZoomIn size={13} /></button>
            <button onClick={() => setZoom(1)} className="p-1.5 rounded hover:bg-muted text-muted-foreground"><RotateCcw size={13} /></button>
            <div className="w-px h-4 bg-border mx-1" />
            <button
              onClick={() => setShowBoxes((b) => !b)}
              className={`p-1.5 rounded hover:bg-muted ${showBoxes ? "text-primary" : "text-muted-foreground"}`}
            >
              {showBoxes ? <Eye size={13} /> : <EyeOff size={13} />}
            </button>
          </div>
        </div>

        {/* Image — natural height, no flex-1 */}
        <div
          className="relative bg-muted/20"
          style={{ cursor: zoom > 1 ? "grab" : "default" }}
        >
          {loadingPage && (
            <div className="flex items-center justify-center h-full">
              <Loader2 size={20} className="animate-spin text-muted-foreground" />
            </div>
          )}
          {!loadingPage && !pageImage && (
            <div className="flex items-center justify-center h-full">
              <p className="text-xs text-muted-foreground">No image</p>
            </div>
          )}
          {pageImage && (
            <div
              className="relative w-full"
              style={{ transform: `scale(${zoom})`, transformOrigin: "top left" }}
            >
              <img
                ref={imgRef}
                src={pageImage}
                alt={`Page ${currentPage}`}
                onLoad={(e) => {
                  const img = e.currentTarget
                  setImgNatural({ w: img.naturalWidth, h: img.naturalHeight })
                }}
                className="block w-full h-auto"
                draggable={false}
              />

              {showBoxes && imgRef.current && blocks.map((box, i) => {
                const [x1, y1, x2, y2] = box.bbox ?? [0, 0, 0, 0]
                const dw = imgRef.current!.clientWidth
                const dh = imgRef.current!.clientHeight
                const color = getColor(box.category)
                const isActive = selectedIdx === i || hoveredIdx === i

                return (
                  <div
                    key={i}
                    className="absolute transition-all duration-75"
                    style={{
                      left: `${x1 * dw / pageW}px`,
                      top: `${y1 * dh / pageH}px`,
                      width: `${(x2 - x1) * dw / pageW}px`,
                      height: `${(y2 - y1) * dh / pageH}px`,
                      backgroundColor: isActive ? color.bg.replace(/[\d.]+\)$/, "0.3)") : color.bg,
                      border: `${selectedIdx === i ? 2 : 1.5}px solid ${isActive ? color.label : color.border}`,
                      cursor: "pointer",
                      zIndex: isActive ? 50 : 10,
                      outline: selectedIdx === i ? `2px solid ${color.label}` : "none",
                      outlineOffset: "1px",
                    }}
                    onClick={() => setSelectedIdx(i === selectedIdx ? null : i)}
                    onMouseEnter={() => setHoveredIdx(i)}
                    onMouseLeave={() => setHoveredIdx(null)}
                  />
                )
              })}
            </div>
          )}
        </div>

        {/* Legend */}
        {showBoxes && activeCategories.length > 0 && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-1.5 bg-muted/40 border-t shrink-0">
            {activeCategories.map((cat) => {
              const c = getColor(cat)
              return (
                <span key={cat} className="flex items-center gap-1 text-[11px]">
                  <span className="w-2.5 h-2.5 border" style={{ backgroundColor: c.bg, borderColor: c.label }} />
                  <span className="text-muted-foreground">{cat}</span>
                </span>
              )
            })}
            <span className="text-[10px] text-muted-foreground ml-auto">{blocks.length} blocks</span>
          </div>
        )}
      </div>

      {/* ── RIGHT: block list + edit — 50%, sticky so it stays in view ──── */}
      <div className="w-1/2 flex flex-col sticky top-0 self-start" style={{ maxHeight: "100vh" }}>

        {/* Header */}
        <div className="px-3 py-2 bg-muted/40 border-b shrink-0 flex items-center justify-between">
          <span className="text-xs font-medium">OCR Content</span>
          <span className="text-[10px] text-muted-foreground">{blocks.length} blocks · p.{currentPage}</span>
        </div>

        {/* Scrollable block list */}
        <div className="overflow-y-auto flex-1">
          {blocks.length === 0 && (
            <p className="text-xs text-muted-foreground text-center py-8">No blocks on this page</p>
          )}

          {blocks.map((box, i) => {
            const color = getColor(box.category)
            const isSelected = selectedIdx === i
            const isEditing = editingIdx === i
            const isPicture = box.category === "Picture" || box.category === "Figure"
            const indent = getIndent(box.category)

            return (
              <div
                key={i}
                ref={(el) => { blockRefs.current[i] = el }}
                className={`border-b py-2 cursor-pointer transition-colors text-xs ${
                  isSelected ? "bg-primary/5" : "hover:bg-muted/40"
                }`}
                style={{
                  borderLeft: `3px solid ${isSelected ? color.label : "transparent"}`,
                  paddingLeft: `${8 + indent * 16}px`,
                  paddingRight: "12px",
                }}
                onClick={() => { if (!isEditing) setSelectedIdx(i === selectedIdx ? null : i) }}
              >
                {/* Category badge + edit button */}
                <div className="flex items-center gap-1.5 mb-1">
                  <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-sm ${color.badge}`}>
                    {box.category}
                  </span>
                  {isSelected && !isEditing && (
                    <button
                      className="ml-auto p-0.5 hover:bg-muted text-muted-foreground hover:text-foreground rounded"
                      onClick={(e) => { e.stopPropagation(); startEdit(i, box.text ?? "") }}
                      title="Edit"
                    >
                      <Pencil size={11} />
                    </button>
                  )}
                </div>

                {/* Content */}
                {isEditing ? (
                  <div className="space-y-1.5" onClick={(e) => e.stopPropagation()}>
                    <Textarea
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      className="text-xs min-h-[80px] resize-y rounded-none"
                      autoFocus
                    />
                    <div className="flex gap-1 justify-end">
                      <Button size="sm" variant="ghost" className="h-6 px-2 text-xs gap-1 rounded-none" onClick={cancelEdit}>
                        <X size={10} /> Cancel
                      </Button>
                      <Button size="sm" className="h-6 px-2 text-xs gap-1 rounded-none" onClick={() => saveEdit(i)} disabled={saving}>
                        {saving ? <Loader2 size={10} className="animate-spin" /> : <Check size={10} />}
                        Save
                      </Button>
                    </div>
                  </div>
                ) : isPicture && !box.text ? (
                  <p className="text-muted-foreground italic text-xs">[No caption — re-extract to generate]</p>
                ) : !box.text ? (
                  <p className="italic opacity-40 text-xs">empty</p>
                ) : (
                  <div className="ocr-md text-xs leading-relaxed text-muted-foreground">
                    <ReactMarkdown
                      remarkPlugins={[remarkMath]}
                      rehypePlugins={[rehypeKatex, rehypeRaw]}
                    >
                      {box.text}
                    </ReactMarkdown>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
