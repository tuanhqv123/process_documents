import { useEffect, useState } from "react"
import { Plus, FolderOpen, FileText, Trash2, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { StatusBadge } from "@/components/status-badge"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import { api } from "@/api/client"
import type { Document, Workspace } from "@/types"

interface WorkspacesPageProps {
  workspaces: Workspace[]
  allDocuments: Document[]
  onWorkspacesChanged: (workspaces: Workspace[]) => void
}

export function WorkspacesPage({
  workspaces,
  allDocuments,
  onWorkspacesChanged,
}: WorkspacesPageProps) {
  const [selectedWs, setSelectedWs] = useState<Workspace | null>(
    workspaces[0] ?? null
  )
  const [wsDocs, setWsDocs] = useState<Document[]>([])
  const [showCreate, setShowCreate] = useState(false)
  const [showAddDoc, setShowAddDoc] = useState(false)
  const [newName, setNewName] = useState("")
  const [creating, setCreating] = useState(false)

  // Load docs for selected workspace
  useEffect(() => {
    if (!selectedWs) return
    api.workspaces.documents(selectedWs.id).then(setWsDocs)
  }, [selectedWs?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleCreateWorkspace = async () => {
    if (!newName.trim()) return
    setCreating(true)
    try {
      const ws = await api.workspaces.create(newName.trim())
      const updated = [ws, ...workspaces]
      onWorkspacesChanged(updated)
      setSelectedWs(ws)
      setNewName("")
      setShowCreate(false)
    } finally {
      setCreating(false)
    }
  }

  const handleDeleteWorkspace = async (ws: Workspace) => {
    if (!confirm(`Delete workspace "${ws.name}"? Documents will not be deleted.`)) return
    await api.workspaces.delete(ws.id)
    const updated = workspaces.filter((w) => w.id !== ws.id)
    onWorkspacesChanged(updated)
    if (selectedWs?.id === ws.id) setSelectedWs(updated[0] ?? null)
  }

  const handleAddDoc = async (doc: Document) => {
    if (!selectedWs) return
    await api.workspaces.addDocument(selectedWs.id, doc.id)
    setWsDocs((prev) => [...prev, doc])
    setShowAddDoc(false)
    // Update doc_count
    onWorkspacesChanged(
      workspaces.map((w) =>
        w.id === selectedWs.id ? { ...w, doc_count: w.doc_count + 1 } : w
      )
    )
  }

  const handleRemoveDoc = async (docId: number) => {
    if (!selectedWs) return
    await api.workspaces.removeDocument(selectedWs.id, docId)
    setWsDocs((prev) => prev.filter((d) => d.id !== docId))
    onWorkspacesChanged(
      workspaces.map((w) =>
        w.id === selectedWs.id ? { ...w, doc_count: Math.max(0, w.doc_count - 1) } : w
      )
    )
  }

  const availableDocs = allDocuments.filter(
    (d) => !wsDocs.some((wd) => wd.id === d.id)
  )

  return (
    <div className="flex h-full">
      {/* Workspace list */}
      <div className="w-56 border-r shrink-0 flex flex-col">
        <div className="flex items-center justify-between p-3 border-b">
          <span className="text-sm font-medium">Workspaces</span>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 w-7 p-0"
            onClick={() => setShowCreate(true)}
          >
            <Plus className="h-4 w-4" />
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {workspaces.length === 0 ? (
            <p className="text-xs text-muted-foreground p-3">No workspaces yet</p>
          ) : (
            workspaces.map((ws) => (
              <div
                key={ws.id}
                onClick={() => setSelectedWs(ws)}
                className={`group flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-muted/50 transition-colors ${
                  selectedWs?.id === ws.id ? "bg-muted" : ""
                }`}
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate">{ws.name}</p>
                  <p className="text-xs text-muted-foreground">{ws.doc_count} docs</p>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 w-6 p-0 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                  onClick={(e) => { e.stopPropagation(); handleDeleteWorkspace(ws) }}
                >
                  <Trash2 className="h-3 w-3 text-destructive" />
                </Button>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Workspace content */}
      <div className="flex-1 p-6 space-y-4 overflow-y-auto">
        {!selectedWs ? (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
            <FolderOpen className="h-12 w-12" />
            <p className="text-sm">Select or create a workspace</p>
            <Button onClick={() => setShowCreate(true)} variant="outline" size="sm">
              <Plus className="h-4 w-4 mr-1" /> New Workspace
            </Button>
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between">
              <div>
                <h2 className="font-semibold text-lg">{selectedWs.name}</h2>
                <p className="text-sm text-muted-foreground">
                  {wsDocs.length} document{wsDocs.length !== 1 ? "s" : ""}
                </p>
              </div>
              <Button
                size="sm"
                variant="outline"
                className="gap-2"
                onClick={() => setShowAddDoc(true)}
                disabled={availableDocs.length === 0}
              >
                <Plus className="h-4 w-4" />
                Add from Dataset
              </Button>
            </div>

            {wsDocs.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-40 gap-2 text-muted-foreground">
                <FileText className="h-8 w-8" />
                <p className="text-sm">No documents in this workspace</p>
                <p className="text-xs">Add documents from your dataset</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {wsDocs.map((doc) => (
                  <div
                    key={doc.id}
                    className="group border rounded-lg p-4 space-y-3 hover:border-primary/40 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <FileText className="h-5 w-5 text-muted-foreground shrink-0" />
                        <span className="font-medium text-sm truncate">{doc.filename}</span>
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
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
                          <span>{doc.chunk_count} chunks</span>
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
      </div>

      {/* Create workspace dialog */}
      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>New Workspace</DialogTitle>
            <DialogDescription>Create a workspace to group related documents.</DialogDescription>
          </DialogHeader>
          <Input
            placeholder="Workspace name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleCreateWorkspace()}
          />
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button onClick={handleCreateWorkspace} disabled={!newName.trim() || creating}>
              {creating ? "Creating…" : "Create"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Add document dialog */}
      <Dialog open={showAddDoc} onOpenChange={setShowAddDoc}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Add Documents</DialogTitle>
            <DialogDescription>Choose documents from your dataset.</DialogDescription>
          </DialogHeader>
          <div className="space-y-2 max-h-72 overflow-y-auto">
            {availableDocs.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">
                All documents are already in this workspace
              </p>
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
