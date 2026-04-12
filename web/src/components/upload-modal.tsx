import { useRef, useState } from "react"
import { Upload, FileText } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import { api } from "@/api/client"
import type { Document } from "@/types"

interface UploadModalProps {
  open: boolean
  onClose: () => void
  onUploaded: (doc: Document) => void
}

export function UploadModal({ open, onClose, onUploaded }: UploadModalProps) {
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState("")
  const inputRef = useRef<HTMLInputElement>(null)

  const handleFile = (f: File) => {
    const lower = f.name.toLowerCase()
    if (!lower.endsWith(".pdf") && !lower.endsWith(".pptx") && !lower.endsWith(".ppt")) {
      setError("Only PDF and PPTX files are supported")
      return
    }
    setError("")
    setFile(f)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) handleFile(f)
  }

  const handleSubmit = async () => {
    if (!file) return
    setUploading(true)
    setError("")
    try {
      const doc = await api.documents.upload(file)
      onUploaded(doc)
      setFile(null)
      onClose()
    } catch (e) {
      setError(String(e))
    } finally {
      setUploading(false)
    }
  }

  const handleClose = () => {
    if (!uploading) {
      setFile(null)
      setError("")
      onClose()
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Upload Document</DialogTitle>
          <DialogDescription>
            The document will be processed and added to your dataset.
          </DialogDescription>
        </DialogHeader>

        {/* Drop zone */}
        <div
          className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
            dragging
              ? "border-primary bg-primary/5"
              : "border-muted-foreground/25 hover:border-primary/50"
          }`}
          onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,.pptx,.ppt"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) handleFile(f)
            }}
          />
          {file ? (
            <div className="flex flex-col items-center gap-2">
              <FileText className="h-10 w-10 text-primary" />
              <p className="font-medium text-sm">{file.name}</p>
              <p className="text-xs text-muted-foreground">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-2">
              <Upload className="h-10 w-10 text-muted-foreground" />
              <p className="font-medium text-sm">Drag & drop a PDF or PPTX here</p>
              <p className="text-xs text-muted-foreground">or click to browse</p>
            </div>
          )}
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={handleClose} disabled={uploading}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={!file || uploading}>
            {uploading ? "Uploading…" : "Upload"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
