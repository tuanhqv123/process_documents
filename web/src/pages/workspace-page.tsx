import { useEffect, useState, useRef } from "react"
import { FileText, Plus, Trash2, X, Search, Loader2, ChevronRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { StatusBadge } from "@/components/status-badge"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import { api } from "@/api/client"
import type { Document, Workspace, SearchResult } from "@/types"

const CATEGORY_COLORS: Record<string, string> = {
  Title: "bg-purple-100 text-purple-700",
  "Section-header": "bg-blue-100 text-blue-700",
  Text: "bg-gray-100 text-gray-700",
  Table: "bg-orange-100 text-orange-700",
  Figure: "bg-green-100 text-green-700",
  Picture: "bg-green-100 text-green-700",
  Formula: "bg-pink-100 text-pink-700",
  Caption: "bg-yellow-100 text-yellow-700",
  "List-item": "bg-gray-100 text-gray-700",
  Footnote: "bg-gray-100 text-gray-500",
}

interface WorkspacePageProps {
  workspace: Workspace
  allDocuments: Document[]
  onWorkspaceUpdated: (ws: Workspace) => void
  onWorkspaceDeleted: (id: number) => void
}

export function WorkspacePage({
  workspace,
  allDocuments,
  onWorkspaceUpdated,
  onWorkspaceDeleted,
}: WorkspacePageProps) {
  const [wsDocs, setWsDocs] = useState<Document[]>([])
  const [showAddDoc, setShowAddDoc] = useState(false)

  // Search
  const [query, setQuery] = useState("")
  const [results, setResults] = useState<SearchResult[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api.workspaces.documents(workspace.id).then(setWsDocs)
  }, [workspace.id])

  // Reset search when workspace changes
  useEffect(() => {
    setQuery("")
    setResults(null)
    setSearchError(null)
  }, [workspace.id])

  const handleSearch = async (e?: React.FormEvent) => {
    e?.preventDefault()
    if (!query.trim()) return
    setSearching(true)
    setSearchError(null)
    try {
      const res = await api.workspaces.search(workspace.id, query.trim())
      setResults(res)
    } catch (err: unknown) {
      setSearchError(err instanceof Error ? err.message : "Search failed")
      setResults([])
    } finally {
      setSearching(false)
    }
  }

  const handleAddDoc = async (doc: Document) => {
    await api.workspaces.addDocument(workspace.id, doc.id)
    setWsDocs((prev) => [...prev, doc])
    onWorkspaceUpdated({ ...workspace, doc_count: workspace.doc_count + 1 })
    setShowAddDoc(false)
  }

  const handleRemoveDoc = async (docId: number) => {
    await api.workspaces.removeDocument(workspace.id, docId)
    setWsDocs((prev) => prev.filter((d) => d.id !== docId))
    onWorkspaceUpdated({ ...workspace, doc_count: Math.max(0, workspace.doc_count - 1) })
  }

  const handleDelete = async () => {
    if (!confirm(`Delete workspace "${workspace.name}"? Documents will not be deleted.`)) return
    await api.workspaces.delete(workspace.id)
    onWorkspaceDeleted(workspace.id)
  }

  const availableDocs = allDocuments.filter((d) => !wsDocs.some((wd) => wd.id === d.id))
  const readyCount = wsDocs.filter((d) => d.status === "ready").length

  return (
    <div className="p-6 space-y-6">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-semibold text-lg">{workspace.name}</h2>
          <p className="text-sm text-muted-foreground">
            {wsDocs.length} document{wsDocs.length !== 1 ? "s" : ""}
            {readyCount > 0 && <span className="ml-1 text-green-600">· {readyCount} searchable</span>}
          </p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => setShowAddDoc(true)} disabled={availableDocs.length === 0} className="gap-2">
            <Plus className="h-4 w-4" />
            Add from Dataset
          </Button>
          <Button size="sm" variant="destructive" onClick={handleDelete}>
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Search bar */}
      <form onSubmit={handleSearch} className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
          <Input
            ref={inputRef}
            placeholder={readyCount === 0 ? "No ready documents to search yet…" : "Search across documents…"}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            disabled={readyCount === 0}
            className="pl-9"
          />
        </div>
        <Button type="submit" size="sm" disabled={!query.trim() || searching || readyCount === 0} className="gap-2 shrink-0">
          {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          Search
        </Button>
        {results !== null && (
          <Button type="button" variant="ghost" size="sm" onClick={() => { setResults(null); setQuery("") }}>
            <X className="h-4 w-4" />
          </Button>
        )}
      </form>

      {/* Search results */}
      {results !== null && (
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">
            {results.length === 0
              ? "No results found"
              : `${results.length} result${results.length !== 1 ? "s" : ""} for "${query}"`}
          </p>
          {searchError && <p className="text-xs text-destructive">{searchError}</p>}
          {results.map((r) => (
            <div key={r.id} className="border rounded-lg p-4 space-y-2 hover:border-primary/40 transition-colors">
              {/* Breadcrumb */}
              <div className="flex items-center gap-1 flex-wrap text-xs text-muted-foreground">
                <span className="font-medium text-foreground">{r.filename}</span>
                {r.context.split(" > ").slice(0, -1).map((part, i) => (
                  <span key={i} className="flex items-center gap-1">
                    <ChevronRight className="h-3 w-3" />
                    <span>{part}</span>
                  </span>
                ))}
              </div>

              {/* Text */}
              <p className="text-sm leading-relaxed line-clamp-4">{r.text}</p>

              {/* Footer */}
              <div className="flex items-center gap-2 flex-wrap">
                <Badge variant="secondary" className={`text-[10px] h-4 px-1.5 ${CATEGORY_COLORS[r.category] ?? ""}`}>
                  {r.category}
                </Badge>
                <span className="text-xs text-muted-foreground">p.{r.page_num}</span>
                <span className="text-xs text-muted-foreground ml-auto">
                  score {(r.score * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Document grid — hidden while search results are shown */}
      {results === null && (
        <>
          {wsDocs.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-40 gap-2 text-muted-foreground">
              <FileText className="h-8 w-8" />
              <p className="text-sm">No documents in this workspace</p>
              <Button variant="outline" size="sm" onClick={() => setShowAddDoc(true)}>Add from Dataset</Button>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {wsDocs.map((doc) => (
                <div key={doc.id} className="group border rounded-lg p-4 space-y-3 hover:border-primary/40 transition-colors">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <FileText className="h-5 w-5 text-muted-foreground shrink-0" />
                      <span className="font-medium text-sm truncate">{doc.filename}</span>
                    </div>
                    <Button
                      variant="ghost" size="sm"
                      className="h-7 w-7 p-0 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                      onClick={() => handleRemoveDoc(doc.id)}
                    >
                      <X className="h-3.5 w-3.5 text-muted-foreground" />
                    </Button>
                  </div>
                  <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                    {doc.status === "ready" && (
                      <>
                        <span>{doc.page_count} pages</span>
                        <span>{doc.chunk_count} nodes</span>
                      </>
                    )}
                  </div>
                  <StatusBadge status={doc.status} />
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* Add document dialog */}
      <Dialog open={showAddDoc} onOpenChange={setShowAddDoc}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Add Documents</DialogTitle>
            <DialogDescription>Choose documents from your dataset to add to this workspace.</DialogDescription>
          </DialogHeader>
          <div className="space-y-2 max-h-72 overflow-y-auto">
            {availableDocs.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">All documents are already in this workspace</p>
            ) : (
              availableDocs.map((doc) => (
                <div
                  key={doc.id}
                  onClick={() => handleAddDoc(doc)}
                  className="flex items-center justify-between p-3 border rounded-lg cursor-pointer hover:border-primary/50 hover:bg-muted/50 transition-colors"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
                    <span className="text-sm truncate">{doc.filename}</span>
                  </div>
                  <StatusBadge status={doc.status} />
                </div>
              ))
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
