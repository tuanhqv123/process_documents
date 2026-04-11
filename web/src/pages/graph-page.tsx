import { useEffect, useState, useCallback, useRef } from "react"
import ForceGraph2D, { type ForceGraphMethods } from "react-force-graph-2d"
import { api } from "@/api/client"
import type { GraphNode } from "@/types"
import { Loader2, RefreshCw, ZoomIn, ZoomOut, Maximize2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useTheme } from "@/components/theme-provider"

// ── Colors per category ────────────────────────────────────────────────────────
const CATEGORY_COLOR: Record<string, string> = {
  Document:         "#e2e8f0",
  Page:             "#64748b",
  Title:            "#f87171",
  "Section-header": "#fb923c",
  Text:             "#60a5fa",
  "List-item":      "#34d399",
  Table:            "#c084fc",
  Picture:          "#f472b6",
  Figure:           "#f472b6",
  Formula:          "#2dd4bf",
  Caption:          "#fbbf24",
  Footnote:         "#94a3b8",
  default:          "#94a3b8",
}

function getColor(cat: string) {
  return CATEGORY_COLOR[cat] ?? CATEGORY_COLOR.default
}

const RANK_SIZE: Record<number, number> = {
  0: 12,
  1: 7,
  2: 6,
  3: 4,
}

// ── Flatten tree ───────────────────────────────────────────────────────────────
interface FlatNode {
  id: string
  label: string
  category: string
  page_num: number
  rank: number
  color: string
  size: number
  x?: number
  y?: number
}

interface FlatLink {
  source: string
  target: string
}

function flattenTree(node: GraphNode, nodes: FlatNode[] = [], links: FlatLink[] = []): { nodes: FlatNode[]; links: FlatLink[] } {
  nodes.push({
    id: String(node.id),
    label: node.text?.slice(0, 60) || `[${node.category}]`,
    category: node.category,
    page_num: node.page_num,
    rank: node.rank,
    color: getColor(node.category),
    size: RANK_SIZE[node.rank] ?? 4,
  })
  node.children?.forEach((child) => {
    links.push({ source: String(node.id), target: String(child.id) })
    flattenTree(child, nodes, links)
  })
  return { nodes, links }
}

// ── Props ──────────────────────────────────────────────────────────────────────
interface GraphPageProps {
  docId: number
  docName: string
}

// ── Component ─────────────────────────────────────────────────────────────────
export function GraphPage({ docId, docName }: GraphPageProps) {
  const { theme } = useTheme()
  const isDark = theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches)

  const bgColor   = isDark ? "#0a0f1a" : "#f8fafc"
  const linkColor = isDark ? "#1e3a5f99" : "#cbd5e199"
  const labelBg   = isDark ? "rgba(10,15,26,0.88)" : "rgba(248,250,252,0.88)"
  const labelFg   = isDark ? "#f1f5f9" : "#1e293b"

  const containerRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<ForceGraphMethods<FlatNode, FlatLink> | undefined>(undefined)
  const [graphData, setGraphData] = useState<{ nodes: FlatNode[]; links: FlatLink[] } | null>(null)
  const [loading, setLoading] = useState(true)
  const [stats, setStats] = useState<{ total: number; leaves: number } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dimensions, setDimensions] = useState({ w: 0, h: 0 })
  const [hoveredNode, setHoveredNode] = useState<FlatNode | null>(null)

  // Fill container dimensions
  useEffect(() => {
    const el = containerRef.current
    console.log("[Graph] containerRef el:", el)
    if (!el) return
    const measure = () => {
      const w = el.offsetWidth
      const h = el.offsetHeight
      const rect = el.getBoundingClientRect()
      console.log("[Graph] measure offsetWidth:", w, "offsetHeight:", h, "getBoundingClientRect:", rect)
      setDimensions({ w, h })
    }
    measure()
    const ro = new ResizeObserver((entries) => {
      const e = entries[0]
      console.log("[Graph] ResizeObserver fired contentRect:", e.contentRect)
      measure()
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.extract.graph(docId)
      if (!data.tree) { setError("No knowledge graph yet — run Train first."); return }
      setStats({ total: data.total_nodes, leaves: data.leaf_nodes })
      setGraphData(flattenTree(data.tree))
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load graph")
    } finally {
      setLoading(false)
    }
  }, [docId])

  useEffect(() => { load() }, [load])

  const paintNode = useCallback((node: FlatNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const x = node.x ?? 0
    const y = node.y ?? 0
    const r = node.size
    const color = node.color
    const isHovered = hoveredNode?.id === node.id

    // Glow
    const glowR = isHovered ? r * 3.5 : r * 2
    const grad = ctx.createRadialGradient(x, y, 0, x, y, glowR)
    grad.addColorStop(0, color + (isDark ? "55" : "33"))
    grad.addColorStop(1, color + "00")
    ctx.beginPath()
    ctx.arc(x, y, glowR, 0, 2 * Math.PI)
    ctx.fillStyle = grad
    ctx.fill()

    // Core
    ctx.beginPath()
    ctx.arc(x, y, r, 0, 2 * Math.PI)
    ctx.fillStyle = isHovered ? color : color + "cc"
    ctx.fill()

    // Label
    const showLabel = isHovered || node.rank === 0 || (node.rank === 1 && globalScale > 0.4) || (node.rank === 2 && globalScale > 0.7)
    if (showLabel) {
      const fontSize = Math.max(9 / globalScale, node.rank === 0 ? 13 : 10)
      ctx.font = `${node.rank <= 1 ? "600 " : ""}${fontSize}px sans-serif`
      ctx.textAlign = "center"
      ctx.textBaseline = "top"
      const label = node.label.length > 35 ? node.label.slice(0, 35) + "…" : node.label
      const tw = ctx.measureText(label).width
      const pad = 3 / globalScale
      const ty = y + r + 3 / globalScale
      ctx.fillStyle = labelBg
      ctx.fillRect(x - tw / 2 - pad, ty - pad, tw + pad * 2, fontSize + pad * 2)
      ctx.fillStyle = isHovered ? (isDark ? "#f8fafc" : "#0f172a") : labelFg
      ctx.fillText(label, x, ty)
    }
  }, [hoveredNode, isDark, labelBg, labelFg])

  return (
    <div className="flex-1 min-h-0 flex flex-col w-full" style={{ background: bgColor }}>
      {/* Toolbar */}
      <div className="flex items-center gap-3 px-4 py-2 border-b shrink-0 flex-wrap">
        <span className="text-sm font-medium truncate max-w-xs">{docName}</span>
        {stats && <span className="text-xs text-muted-foreground">{stats.total} nodes · {stats.leaves} leaves</span>}
        <div className="flex items-center gap-3 ml-2 flex-wrap">
          {["Document", "Title", "Section-header", "Text", "Table", "Picture"].map((cat) => (
            <span key={cat} className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full inline-block" style={{ background: getColor(cat), boxShadow: `0 0 5px ${getColor(cat)}99` }} />
              <span className="text-[10px] text-muted-foreground">{cat}</span>
            </span>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-1">
          <Button size="sm" variant="ghost" className="h-7 w-7 p-0" onClick={() => graphRef.current?.zoom?.(1.5, 300)}><ZoomIn className="h-3.5 w-3.5" /></Button>
          <Button size="sm" variant="ghost" className="h-7 w-7 p-0" onClick={() => graphRef.current?.zoom?.(0.67, 300)}><ZoomOut className="h-3.5 w-3.5" /></Button>
          <Button size="sm" variant="ghost" className="h-7 w-7 p-0" onClick={() => graphRef.current?.zoomToFit?.(400, 40)}><Maximize2 className="h-3.5 w-3.5" /></Button>
          <Button size="sm" variant="ghost" className="h-7 w-7 p-0" onClick={load}><RefreshCw className="h-3.5 w-3.5" /></Button>
        </div>
      </div>

      {/* Canvas container — always mounted so ref is attached on first render */}
      <div ref={containerRef} className="flex-1 min-h-0 relative overflow-hidden">

        {/* Loading overlay */}
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center gap-2 text-muted-foreground z-10">
            <Loader2 className="h-5 w-5 animate-spin" /><span className="text-sm">Loading…</span>
          </div>
        )}

        {/* Error overlay */}
        {!loading && error && (
          <div className="absolute inset-0 flex items-center justify-center text-muted-foreground z-10">
            <p className="text-sm">{error}</p>
          </div>
        )}

        {/* Hover tooltip */}
        {hoveredNode && (
          <div className="absolute bottom-6 left-1/2 -translate-x-1/2 bg-popover border rounded px-3 py-1.5 text-xs pointer-events-none max-w-sm truncate shadow-xl z-20">
            <span className="text-muted-foreground mr-1.5">{hoveredNode.category}{hoveredNode.page_num > 0 ? ` · p${hoveredNode.page_num}` : ""}</span>
            {hoveredNode.label}
          </div>
        )}

        {/* Graph — only render when we have real dimensions */}
        {graphData && dimensions.w > 0 && dimensions.h > 0 && (
          <ForceGraph2D
            ref={graphRef}
            graphData={graphData}
            width={dimensions.w}
            height={dimensions.h}
            backgroundColor={bgColor}
            nodeCanvasObject={paintNode}
            nodeCanvasObjectMode={() => "replace"}
            nodeVal={(n) => (n as FlatNode).size}
            linkColor={() => linkColor}
            linkWidth={0.8}
            linkDirectionalParticles={1}
            linkDirectionalParticleWidth={1.5}
            linkDirectionalParticleColor={() => "#3b82f666"}
            linkDirectionalParticleSpeed={0.003}
            onNodeHover={(node) => setHoveredNode(node as FlatNode | null)}
            onNodeClick={(node) => {
              const n = node as FlatNode
              graphRef.current?.centerAt?.(n.x, n.y, 500)
              graphRef.current?.zoom?.(2, 500)
            }}
            cooldownTicks={300}
            d3AlphaDecay={0.01}
            d3VelocityDecay={0.2}
            enableNodeDrag
            enableZoomInteraction
            onEngineStop={() => graphRef.current?.zoomToFit?.(400, 40)}
          />
        )}
      </div>
    </div>
  )
}
