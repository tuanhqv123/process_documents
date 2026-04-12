import { Badge } from "@/components/ui/badge"
import { Loader2 } from "lucide-react"
import type { Document } from "@/types"

type Status = Document["status"]

const config: Record<Status, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  uploaded:   { label: "Uploaded",   variant: "secondary" },
  extracting: { label: "Extracting", variant: "outline" },
  extracted:  { label: "Extracted",  variant: "outline" },
  ready:      { label: "Ready",      variant: "default" },
  error:      { label: "Error",      variant: "destructive" },
  // legacy statuses
  pending:    { label: "Pending",    variant: "secondary" },
  processing: { label: "Processing", variant: "outline" },
}

export function StatusBadge({ status }: { status: Status }) {
  const { label, variant } = config[status] ?? config.uploaded
  const isSpinning = status === "extracting" || status === "processing"
  return (
    <Badge variant={variant} className="gap-1">
      {isSpinning && <Loader2 className="h-3 w-3 animate-spin" />}
      {label}
    </Badge>
  )
}
