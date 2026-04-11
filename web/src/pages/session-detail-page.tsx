import { useEffect, useState, useCallback, useRef } from "react"
import {
  Radio, Square, ArrowLeft, Loader2, RefreshCw,
  FileText, BookOpen, ChevronRight, Sparkles, Clock,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { api } from "@/api/client"
import type { RecordingSession, SessionRagBlock, RagResult } from "@/types"

interface SessionDetailPageProps {
  session: RecordingSession
  onBack: () => void
  onSessionUpdated: (s: RecordingSession) => void
}

export function SessionDetailPage({
  session: initialSession,
  onBack,
  onSessionUpdated,
}: SessionDetailPageProps) {
  const [session, setSession] = useState(initialSession)
  const [blocks, setBlocks] = useState<SessionRagBlock[]>([])
  const [selectedBlockId, setSelectedBlockId] = useState<number | null>(null)
  const [actionLoading, setActionLoading] = useState(false)
  const [summarizing, setSummarizing] = useState(false)
  const lastBlockEndRef = useRef<string | undefined>(undefined)
  const pollRef = useRef<number | null>(null)

  const loadAll = useCallback(async () => {
    const data = await api.sessions.blocks(session.id)
    setBlocks(data)
    if (data.length > 0) {
      lastBlockEndRef.current = data[data.length - 1].block_end
      setSelectedBlockId(data[data.length - 1].id)
    }
  }, [session.id])

  useEffect(() => { loadAll() }, [loadAll])

  useEffect(() => {
    if (session.status !== "active") {
      if (pollRef.current) clearInterval(pollRef.current)
      return
    }
    pollRef.current = window.setInterval(async () => {
      try {
        const newBlocks = await api.sessions.blocks(session.id, lastBlockEndRef.current)
        if (newBlocks.length > 0) {
          setBlocks(prev => [...prev, ...newBlocks])
          lastBlockEndRef.current = newBlocks[newBlocks.length - 1].block_end
          setSelectedBlockId(newBlocks[newBlocks.length - 1].id)
        }
      } catch (e) {
        console.error("Poll error:", e)
      }
    }, 5000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [session.id, session.status])

  const handleStart = async () => {
    setActionLoading(true)
    try {
      const updated = await api.sessions.start(session.id)
      setSession(updated)
      onSessionUpdated(updated)
    } finally {
      setActionLoading(false)
    }
  }

  const handleStop = async () => {
    setActionLoading(true)
    setSummarizing(true)
    try {
      const updated = await api.sessions.stop(session.id)
      setSession(updated)
      onSessionUpdated(updated)
      const pollSummary = async () => {
        const refreshed = await api.sessions.get(session.id)
        if (refreshed.summary) {
          setSession(refreshed)
          onSessionUpdated(refreshed)
          setSummarizing(false)
        } else {
          setTimeout(pollSummary, 3000)
        }
      }
      setTimeout(pollSummary, 3000)
    } finally {
      setActionLoading(false)
    }
  }

  const handleResummarize = async () => {
    setSummarizing(true)
    try {
      const updated = await api.sessions.summarize(session.id)
      setSession(updated)
      onSessionUpdated(updated)
    } finally {
      setSummarizing(false)
    }
  }

  const selectedBlock = blocks.find(b => b.id === selectedBlockId) ?? null

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b shrink-0 flex-wrap">
        <Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground shrink-0"
          onClick={onBack}>
          <ArrowLeft className="h-4 w-4" /> Back
        </Button>
        <div className="w-px h-4 bg-border shrink-0" />
        <span className="font-medium text-sm truncate">{session.name}</span>
        {session.workspace_name && (
          <Badge variant="outline" className="gap-1 text-xs shrink-0">
            <BookOpen className="h-3 w-3" /> {session.workspace_name}
          </Badge>
        )}
        <Badge
          variant={session.status === "active" ? "default" : "secondary"}
          className="shrink-0"
        >
          {session.status === "active" && (
            <Radio className="h-3 w-3 mr-1 animate-pulse" />
          )}
          {session.status}
        </Badge>
        <div className="ml-auto flex items-center gap-2">
          {session.status === "idle" && (
            <Button size="sm" onClick={handleStart} disabled={actionLoading} className="gap-1.5">
              <Radio className="h-3.5 w-3.5" />
              {actionLoading ? "Starting…" : "Start Recording"}
            </Button>
          )}
          {session.status === "active" && (
            <Button size="sm" variant="destructive" onClick={handleStop}
              disabled={actionLoading} className="gap-1.5">
              <Square className="h-3.5 w-3.5" />
              {actionLoading ? "Stopping…" : "Stop"}
            </Button>
          )}
          {session.status === "stopped" && (
            <Button size="sm" variant="outline" onClick={handleResummarize}
              disabled={summarizing} className="gap-1.5">
              <Sparkles className="h-3.5 w-3.5" />
              {summarizing ? "Summarizing…" : "Re-summarize"}
            </Button>
          )}
        </div>
      </div>

      {/* Split view */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Left: block list */}
        <div className="w-80 shrink-0 border-r flex flex-col">
          <div className="px-3 py-2 text-xs font-medium text-muted-foreground border-b shrink-0 flex items-center gap-2">
            BLOCKS ({blocks.length})
            {session.status === "active" && (
              <span className="flex items-center gap-1 text-green-500 ml-auto">
                <RefreshCw className="h-3 w-3 animate-spin" /> live
              </span>
            )}
          </div>
          <ScrollArea className="flex-1">
            {blocks.length === 0 ? (
              <div className="p-4 text-xs text-muted-foreground text-center">
                {session.status === "active"
                  ? "Waiting for speech… (10 s window)"
                  : "No blocks in this session."}
              </div>
            ) : (
              <div className="flex flex-col">
                {[...blocks].reverse().map(b => (
                  <BlockCard
                    key={b.id}
                    block={b}
                    selected={selectedBlockId === b.id}
                    onClick={() => setSelectedBlockId(b.id)}
                  />
                ))}
              </div>
            )}
          </ScrollArea>
        </div>

        {/* Right: RAG context */}
        <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
          {selectedBlock ? (
            <RagPanel block={selectedBlock} />
          ) : (
            <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
              Select a block to see matched document sections
            </div>
          )}
        </div>
      </div>

      {/* Summary */}
      {session.status === "stopped" && (
        <div className="border-t shrink-0 max-h-64 overflow-y-auto bg-muted/20">
          <div className="px-4 py-2 text-xs font-medium text-muted-foreground flex items-center gap-2 border-b">
            <Sparkles className="h-3.5 w-3.5" /> SESSION SUMMARY
          </div>
          {summarizing ? (
            <div className="px-4 py-3 flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Generating summary…
            </div>
          ) : session.summary ? (
            <div className="px-4 py-3 text-sm whitespace-pre-wrap leading-relaxed">
              {session.summary}
            </div>
          ) : (
            <div className="px-4 py-3 text-sm text-muted-foreground">
              No summary yet.
            </div>
          )}
        </div>
      )}
    </div>
  )
}


// ── Block Card ────────────────────────────────────────────────────────────────

function BlockCard({
  block,
  selected,
  onClick,
}: { block: SessionRagBlock; selected: boolean; onClick: () => void }) {
  const start = new Date(block.block_start).toLocaleTimeString()
  const end = new Date(block.block_end).toLocaleTimeString()
  return (
    <button
      onClick={onClick}
      className={`text-left w-full px-3 py-3 border-b last:border-0 transition-colors hover:bg-muted/50 ${
        selected ? "bg-muted" : ""
      }`}
    >
      <div className="flex items-center gap-1.5 mb-1.5">
        <Clock className="h-3 w-3 text-muted-foreground shrink-0" />
        <span className="text-[10px] text-muted-foreground">
          {start} – {end}
        </span>
        {block.rag_results.length > 0 && (
          <Badge variant="secondary" className="ml-auto text-[10px] h-4 px-1">
            {block.rag_results.length} match{block.rag_results.length !== 1 ? "es" : ""}
          </Badge>
        )}
      </div>
      <div className="flex flex-col gap-0.5">
        {block.transcripts.map(t => (
          <div key={t.id} className="flex gap-1.5 items-baseline">
            <span className="text-[9px] text-muted-foreground shrink-0 tabular-nums">
              {new Date(t.timestamp).toLocaleTimeString()}
            </span>
            <span className="text-xs leading-snug line-clamp-2">{t.text}</span>
          </div>
        ))}
      </div>
    </button>
  )
}


// ── RAG Panel ─────────────────────────────────────────────────────────────────

function RagPanel({ block }: { block: SessionRagBlock }) {
  const [selectedResult, setSelectedResult] = useState<RagResult | null>(
    block.rag_results[0] ?? null
  )

  useEffect(() => {
    setSelectedResult(block.rag_results[0] ?? null)
  }, [block.id])

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b bg-muted/20 shrink-0">
        <div className="text-[10px] text-muted-foreground mb-1 flex items-center gap-2">
          <Clock className="h-3 w-3" />
          {new Date(block.block_start).toLocaleTimeString()} –{" "}
          {new Date(block.block_end).toLocaleTimeString()}
          <span className="ml-1">· {block.transcripts.length} line{block.transcripts.length !== 1 ? "s" : ""}</span>
        </div>
        <p className="text-sm leading-relaxed">{block.combined_text}</p>
      </div>

      {block.rag_results.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
          No matching document sections found for this block
        </div>
      ) : (
        <div className="flex flex-1 min-h-0 overflow-hidden">
          <div className="w-52 shrink-0 border-r overflow-y-auto">
            {block.rag_results.map(r => (
              <button
                key={r.id}
                onClick={() => setSelectedResult(r)}
                className={`w-full text-left px-3 py-2.5 border-b last:border-0 transition-colors hover:bg-muted/50 ${
                  selectedResult?.id === r.id ? "bg-muted" : ""
                }`}
              >
                <div className="flex items-center gap-1 text-[10px] text-muted-foreground mb-0.5">
                  <FileText className="h-3 w-3 shrink-0" />
                  <span className="truncate">{r.filename}</span>
                </div>
                <div className="text-[10px] font-medium">p.{r.page_num} · {r.category}</div>
                <div className="text-[10px] text-muted-foreground mt-0.5">
                  {Math.round(r.score * 100)}% match
                </div>
              </button>
            ))}
          </div>

          {selectedResult && (
            <div className="flex-1 min-w-0 overflow-y-auto p-4 flex flex-col gap-3">
              <div className="flex items-center gap-1 text-xs text-muted-foreground flex-wrap">
                {selectedResult.context.split(" > ").map((part, i, arr) => (
                  <span key={i} className="flex items-center gap-1">
                    {i > 0 && <ChevronRight className="h-3 w-3 shrink-0" />}
                    <span className={i === arr.length - 1 ? "text-foreground font-medium" : ""}>
                      {part}
                    </span>
                  </span>
                ))}
              </div>

              <div className="rounded-lg overflow-hidden border bg-muted/30">
                <img
                  src={api.extract.pageImageUrl(selectedResult.doc_id, selectedResult.page_num)}
                  alt={`Page ${selectedResult.page_num} of ${selectedResult.filename}`}
                  className="w-full object-contain max-h-72"
                  onError={(e) => {
                    (e.target as HTMLImageElement).style.display = "none"
                  }}
                />
              </div>

              <div className="text-xs border rounded-lg p-3 bg-muted/20 leading-relaxed">
                {selectedResult.text}
              </div>

              <div className="text-[10px] text-muted-foreground">
                Score: {(selectedResult.score * 100).toFixed(1)}% · {selectedResult.filename} p.{selectedResult.page_num}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
