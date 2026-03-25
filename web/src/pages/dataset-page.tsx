import { useState, useEffect } from "react";
import { Plus, MoreVertical, Eye, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { StatusBadge } from "@/components/status-badge";
import { UploadModal } from "@/components/upload-modal";
import { api } from "@/api/client";
import type { Document } from "@/types";

interface DatasetPageProps {
  documents: Document[];
  selectedDocId: number | null;
  onSelectDoc: (doc: Document) => void;
  onDocumentAdded: (doc: Document) => void;
  onDocumentDeleted: (id: number) => void;
  onDocumentUpdated: (doc: Document) => void;
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function DatasetPage({
  documents,
  selectedDocId,
  onSelectDoc,
  onDocumentAdded,
  onDocumentDeleted,
}: DatasetPageProps) {
  const [showUpload, setShowUpload] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Document | null>(null);
  const [deleting, setDeleting] = useState(false);

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.documents.delete(deleteTarget.id);
      onDocumentDeleted(deleteTarget.id);
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b shrink-0">
        <div>
          <p className="font-semibold text-lg">Dataset</p>
          <p className="text-sm text-muted-foreground">
            {documents.length} document{documents.length !== 1 ? "s" : ""} in
            your library
          </p>
        </div>
        <Button onClick={() => setShowUpload(true)} size="sm" className="gap-2">
          <Plus className="h-4 w-4" />
          Upload PDF
        </Button>
      </div>

      {/* Table */}
      {documents.length === 0 ? (
        <div className="flex flex-col items-center justify-center flex-1 gap-3 text-muted-foreground">
          <p className="text-sm font-medium">No documents yet</p>
          <p className="text-xs">Upload a PDF to get started</p>
          <Button
            onClick={() => setShowUpload(true)}
            variant="outline"
            size="sm"
          >
            Upload PDF
          </Button>
        </div>
      ) : (
        <div className="flex-1 overflow-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead className="w-24">Size</TableHead>
                <TableHead className="w-20">Pages</TableHead>
                <TableHead className="w-28">Status</TableHead>
                <TableHead>Workspaces</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {documents.map((doc) => (
                <TableRow
                  key={doc.id}
                  className={`cursor-pointer ${selectedDocId === doc.id ? "bg-muted/50" : ""}`}
                  onClick={() => onSelectDoc(doc)}
                >
                  <TableCell className="font-medium max-w-xs truncate">
                    {doc.filename}
                  </TableCell>
                  <TableCell className="text-muted-foreground text-sm">
                    {formatBytes(doc.file_size)}
                  </TableCell>
                  <TableCell className="text-muted-foreground text-sm">
                    {doc.status === "ready" ? doc.page_count : "—"}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={doc.status} />
                  </TableCell>
                  <TableCell>
                    <WorkspaceTags docId={doc.id} />
                  </TableCell>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 w-7 p-0"
                        >
                          <MoreVertical className="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => onSelectDoc(doc)}>
                          <Eye className="h-4 w-4 mr-2" />
                          View
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          className="text-destructive focus:text-destructive"
                          onClick={() => setDeleteTarget(doc)}
                        >
                          <Trash2 className="h-4 w-4 mr-2" />
                          Delete
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <UploadModal
        open={showUpload}
        onClose={() => setShowUpload(false)}
        onUploaded={onDocumentAdded}
      />

      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete document?</AlertDialogTitle>
            <AlertDialogDescription>
              <strong>{deleteTarget?.filename}</strong> will be permanently
              deleted along with all its chunks and images. This cannot be
              undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDelete}
              disabled={deleting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleting ? "Deleting…" : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

// Lazy-load workspace tags per row
function WorkspaceTags({ docId }: { docId: number }) {
  const [tags, setTags] = useState<{ id: number; name: string }[] | null>(null);

  useEffect(() => {
    api.documents.workspaces(docId).then(setTags).catch(() => setTags([]));
  }, [docId]);

  if (!tags || tags.length === 0) return <span className="text-muted-foreground text-xs">—</span>;

  return (
    <div className="flex flex-wrap gap-1">
      {tags.map((ws) => (
        <span
          key={ws.id}
          className="inline-flex items-center rounded-full bg-secondary px-2 py-0.5 text-xs font-medium"
        >
          {ws.name}
        </span>
      ))}
    </div>
  );
}
