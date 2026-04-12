import { useEffect, useState, useCallback, useRef } from "react"
import {
  Radio, Square, ArrowLeft, Loader2, RefreshCw, Mic,
  FileText, Sparkles, Clock, ChevronDown, ChevronUp,
} from "lucide-react"

import ReactMarkdown from "react-markdown"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
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
  const [liveTranscripts, setLiveTranscripts] = useState<{ id: number; text: string; timestamp: string }[]>([])
  const [selectedResult, setSelectedResult] = useState<RagResult | null>(null)
  const [actionLoading, setActionLoading] = useState(false)
  const [summarizing, setSummarizing] = useState(false)
  const [summaryOpen, setSummaryOpen] = useState(false)
  const lastBlockEndRef = useRef<string | undefined>(undefined)
  const lastTranscriptRef = useRef<string | undefined>(undefined)
  const pollRef = useRef<number | null>(null)
  const sessionIdRef = useRef(session.id)
  sessionIdRef.current = session.id

  const loadAll = useCallback(async () => {
    const data = await api.sessions.blocks(session.id)
    setBlocks(data)
    if (data.length > 0) {
      lastBlockEndRef.current = data[data.length - 1].block_end
      const last = data[data.length - 1]
      if (last.rag_results.length > 0) setSelectedResult(last.rag_results[0])
    }
  }, [session.id])

  useEffect(() => { loadAll() }, [loadAll])

  // Auto-open summary strip when summary arrives
  useEffect(() => {
    if (session.summary) setSummaryOpen(true)
  }, [session.summary])

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const startPolling = useCallback(() => {
    if (pollRef.current !== null) return // already running
    pollRef.current = window.setInterval(async () => {
      try {
        const sid = sessionIdRef.current
        const newTs = await api.sessions.transcripts(sid, lastTranscriptRef.current)
        if (newTs.length > 0) {
          setLiveTranscripts(prev => [...prev, ...newTs])
          lastTranscriptRef.current = newTs[newTs.length - 1].timestamp
        }
        const newBlocks = await api.sessions.blocks(sid, lastBlockEndRef.current)
        if (newBlocks.length > 0) {
          setBlocks(prev => [...prev, ...newBlocks])
          lastBlockEndRef.current = newBlocks[newBlocks.length - 1].block_end
          const last = newBlocks[newBlocks.length - 1]
          if (last.rag_results.length > 0) setSelectedResult(last.rag_results[0])
        }
      } catch (e) {
        console.error("Poll error:", e)
      }
    }, 2000)
  }, [])

  // Start/stop polling based on session status (handles mount with active session)
  useEffect(() => {
    if (session.status === "active") {
      startPolling()
    } else {
      stopPolling()
    }
    return stopPolling
  }, [session.status, startPolling, stopPolling])

  const handleStart = async () => {
    setActionLoading(true)
    try {
      const updated = await api.sessions.start(session.id)
      setSession(updated)
      onSessionUpdated(updated)
      startPolling() // start immediately — don't wait for useEffect re-run
    } finally {
      setActionLoading(false)
    }
  }

  const handleStop = async () => {
    setActionLoading(true)
    setSummarizing(true)
    stopPolling()
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
          <Badge variant="outline" className="text-xs shrink-0">
            {session.workspace_name}
          </Badge>
        )}
        <Badge variant={session.status === "active" ? "default" : "secondary"} className="shrink-0">
          {session.status === "active" && <Radio className="h-3 w-3 mr-1 animate-pulse" />}
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

      {/* Main split */}
      <div className="flex flex-1 min-h-0 overflow-hidden">

        {/* Left: blocks + nested RAG */}
        <div className="w-1/2 shrink-0 border-r flex flex-col">
          <div className="flex-1 min-h-0 overflow-y-auto">
            {/* Live transcript feed */}
            {session.status === "active" && liveTranscripts.length > 0 && (
              <div className="border-b bg-muted/20 px-3 py-2">
                <div className="text-[10px] font-medium text-muted-foreground mb-1.5 flex items-center gap-1.5">
                  <Mic className="h-3 w-3" />
                  LIVE TRANSCRIPT
                </div>
                <div className="flex flex-col gap-1 max-h-32 overflow-y-auto">
                  {[...liveTranscripts].reverse().slice(0, 10).map(t => (
                    <div key={t.id} className="flex gap-1.5 items-baseline">
                      <span className="text-[9px] text-muted-foreground shrink-0 tabular-nums">
                        {new Date(t.timestamp).toLocaleTimeString()}
                      </span>
                      <span className="text-sm leading-snug">{t.text}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {blocks.length === 0 && liveTranscripts.length === 0 ? (
              <div className="p-4 text-xs text-muted-foreground text-center">
                {session.status === "active"
                  ? "Waiting for speech…"
                  : "No blocks recorded yet."}
              </div>
            ) : blocks.length === 0 ? null : (
              <div className="flex flex-col divide-y">
                {[...blocks].reverse().map(b => (
                  <BlockRow
                    key={b.id}
                    block={b}
                    selectedResultId={selectedResult?.id ?? null}
                    onSelectResult={setSelectedResult}
                  />
                ))}
              </div>
            )}
            {session.status === "active" && (
              <div className="px-3 py-2 flex items-center gap-1.5 text-[10px] text-green-500">
                <RefreshCw className="h-3 w-3 animate-spin" /> live
              </div>
            )}
          </div>
        </div>

        {/* Right: page view */}
        <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
          {selectedResult ? (
            <div className="flex-1 overflow-y-auto min-h-0">
              <PageImage
                src={api.extract.pageImageUrl(selectedResult.doc_id, selectedResult.page_num)}
                bbox={selectedResult.bbox}
                alt={`Page ${selectedResult.page_num}`}
              />
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
              Click a matched section to view its page
            </div>
          )}
        </div>
      </div>

      {/* Summary strip — only when stopped */}
      {session.status === "stopped" && (
        <div className="border-t shrink-0">
          <button
            onClick={() => setSummaryOpen(o => !o)}
            className="w-full px-4 py-2 flex items-center gap-2 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
          >
            <Sparkles className="h-3.5 w-3.5" />
            SESSION SUMMARY
            {summarizing && <Loader2 className="h-3 w-3 animate-spin ml-1" />}
            <span className="ml-auto">
              {summaryOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </span>
          </button>
          {summaryOpen && (
            <div className="max-h-64 overflow-y-auto border-t">
              {summarizing ? (
                <div className="px-4 py-3 flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" /> Generating summary…
                </div>
              ) : session.summary ? (
                <div className="px-4 py-3 prose prose-sm dark:prose-invert max-w-none">
                  <ReactMarkdown>{session.summary}</ReactMarkdown>
                </div>
              ) : (
                <div className="px-4 py-3 text-sm text-muted-foreground">
                  No summary yet. Click Re-summarize to generate one.
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}


// ── Block Row ─────────────────────────────────────────────────────────────────

function BlockRow({
  block,
  selectedResultId,
  onSelectResult,
}: {
  block: SessionRagBlock
  selectedResultId: number | null
  onSelectResult: (r: RagResult) => void
}) {
  const start = new Date(block.block_start).toLocaleTimeString()
  const end = new Date(block.block_end).toLocaleTimeString()

  return (
    <div className="px-3 pt-3 pb-3">
      {/* Time */}
      <div className="flex items-center gap-1.5 mb-1.5">
        <Clock className="h-3 w-3 text-muted-foreground shrink-0" />
        <span className="text-[10px] text-muted-foreground tabular-nums">
          {start} – {end}
        </span>
      </div>

      {/* Transcript lines */}
      <div className="flex flex-col gap-1 mb-2">
        {block.transcripts.map(t => (
          <div key={t.id} className="flex gap-1.5 items-baseline">
            <span className="text-[9px] text-muted-foreground shrink-0 tabular-nums">
              {new Date(t.timestamp).toLocaleTimeString()}
            </span>
            <span className="text-sm leading-snug">{t.text}</span>
          </div>
        ))}
      </div>

      {/* Nested RAG results */}
      {block.rag_results.length > 0 && (
        <div className="flex flex-col gap-1 border-l-2 border-muted ml-1 pl-2.5">
          {block.rag_results.map(r => (
            <button
              key={r.id}
              onClick={() => onSelectResult(r)}
              className={`text-left w-full rounded px-2 py-1.5 transition-colors hover:bg-muted/60 ${
                selectedResultId === r.id ? "bg-muted" : ""
              }`}
            >
              <div className="flex items-center gap-1 mb-1">
                <FileText className="h-3 w-3 text-muted-foreground shrink-0" />
                <span className="text-[10px] font-medium truncate">{r.filename}</span>
                <span className="text-[9px] text-muted-foreground ml-auto shrink-0">
                  p.{r.page_num} · {r.category}
                </span>
              </div>
              <RagPreview result={r} />
            </button>
          ))}
        </div>
      )}
    </div>
  )
}


// ── RAG Result Preview (category-aware) ──────────────────────────────────────

function RagPreview({ result }: { result: RagResult }) {
  const { category, text } = result

  if (category === "Table") {
    return (
      <div
        className={`
          text-[9px] overflow-auto max-h-32 rounded border border-border bg-muted/10 p-1
          [&_table]:w-full [&_table]:border-collapse
          [&_td]:border [&_td]:border-border [&_td]:px-1 [&_td]:py-0.5 [&_td]:align-top
          [&_th]:border [&_th]:border-border [&_th]:px-1 [&_th]:py-0.5 [&_th]:font-medium [&_th]:bg-muted/30
        `}
        dangerouslySetInnerHTML={{ __html: text }}
      />
    )
  }

  if (category === "Picture" || category === "Figure") {
    return (
      <p className="text-[10px] text-muted-foreground leading-relaxed line-clamp-2 italic">
        {text}
      </p>
    )
  }

  // Text, Caption, List-item, etc.
  return (
    <p className="text-[10px] text-muted-foreground leading-relaxed line-clamp-3">
      {text}
    </p>
  )
}


// ── Page Image with bbox highlight ────────────────────────────────────────────

function PageImage({ src, bbox, alt }: { src: string; bbox: number[]; alt: string }) {
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null)

  useEffect(() => { setNatural(null) }, [src])

  const hasBox = bbox && bbox.length === 4

  return (
    <div className="relative overflow-hidden bg-muted/30">
      <img
        src={src}
        alt={alt}
        className="w-full block"
        onLoad={(e) => {
          const img = e.currentTarget
          setNatural({ w: img.naturalWidth, h: img.naturalHeight })
        }}
        onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none" }}
      />
      {natural && hasBox && (
        <div
          className="absolute border-2 border-yellow-400 bg-yellow-400/20 pointer-events-none rounded-sm"
          style={{
            left:   `${(bbox[0] / natural.w) * 100}%`,
            top:    `${(bbox[1] / natural.h) * 100}%`,
            width:  `${((bbox[2] - bbox[0]) / natural.w) * 100}%`,
            height: `${((bbox[3] - bbox[1]) / natural.h) * 100}%`,
          }}
        />
      )}
    </div>
  )
}
