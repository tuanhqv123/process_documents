import { useEffect, useState } from "react"
import { FileText, Plus, Trash2, X } from "lucide-react"
import { Button } from "@/components/ui/button"
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
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    api.workspaces.documents(workspace.id).then(setWsDocs).finally(() => setLoading(false))
  }, [workspace.id])

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

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-semibold text-lg">{workspace.name}</h2>
          <p className="text-sm text-muted-foreground">
            {wsDocs.length} document{wsDocs.length !== 1 ? "s" : ""}
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => setShowAddDoc(true)}
            disabled={availableDocs.length === 0}
            className="gap-2"
          >
            <Plus className="h-4 w-4" />
            Add from Dataset
          </Button>
          <Button size="sm" variant="destructive" onClick={handleDelete}>
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Document grid */}
      {loading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : wsDocs.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-40 gap-2 text-muted-foreground">
          <FileText className="h-8 w-8" />
          <p className="text-sm">No documents in this workspace</p>
          <Button variant="outline" size="sm" onClick={() => setShowAddDoc(true)}>
            Add from Dataset
          </Button>
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
                    <span>{doc.image_count} images</span>
                  </>
                )}
              </div>
              <StatusBadge status={doc.status} />
            </div>
          ))}
        </div>
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
