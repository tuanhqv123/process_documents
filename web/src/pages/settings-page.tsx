import { useState, useEffect } from "react"
import { Plus, Trash2, Pencil, CheckCircle2, XCircle, Loader2, Wifi, WifiOff, ChevronDown } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { api } from "@/api/client"
import type { ApiKey } from "@/types"

// ── Types ──────────────────────────────────────────────────────────────────────

type TestStatus = "idle" | "testing" | "ok" | "error"

interface TestState {
  status: TestStatus
  latency_ms: number
  models: string[]
  error: string | null
}

const defaultTest = (): TestState => ({ status: "idle", latency_ms: 0, models: [], error: null })

// ── Small helpers ──────────────────────────────────────────────────────────────

function TestBadge({ state }: { state: TestState }) {
  if (state.status === "idle") return null
  if (state.status === "testing")
    return <span className="flex items-center gap-1 text-xs text-muted-foreground"><Loader2 className="h-3 w-3 animate-spin" /> Testing…</span>
  if (state.status === "ok")
    return <span className="flex items-center gap-1.5 text-xs text-green-600"><CheckCircle2 className="h-3 w-3" />{state.latency_ms}ms · {state.models.length} model{state.models.length !== 1 ? "s" : ""}</span>
  return <span className="flex items-center gap-1.5 text-xs text-destructive"><XCircle className="h-3 w-3" />{state.error ?? "Failed"}</span>
}

function ModelSelect({ models, value, onChange, placeholder }: { models: string[]; value: string; onChange: (v: string) => void; placeholder: string }) {
  if (models.length === 0)
    return <Input placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)} />
  return (
    <div className="relative">
      <select
        className="w-full h-9 rounded-md border border-input bg-background px-3 pr-8 text-sm appearance-none"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">— select model —</option>
        {models.map((m) => <option key={m} value={m}>{m}</option>)}
      </select>
      <ChevronDown className="absolute right-2.5 top-2.5 h-4 w-4 text-muted-foreground pointer-events-none" />
    </div>
  )
}

// ── Add form state ─────────────────────────────────────────────────────────────

const emptyForm = () => ({ label: "", type: "ocr" as "ocr" | "llm", base_url: "", api_key: "", model_name: "" })

// ── Main page ──────────────────────────────────────────────────────────────────

export function SettingsPage() {
  const [keys, setKeys] = useState<ApiKey[]>([])
  const [deleteTarget, setDeleteTarget] = useState<ApiKey | null>(null)

  // Add form
  const [form, setForm] = useState(emptyForm())
  const [adding, setAdding] = useState(false)
  const [addTest, setAddTest] = useState<TestState>(defaultTest())

  // Per-row test state (keyed by id)
  const [rowTest, setRowTest] = useState<Record<number, TestState>>({})

  // Edit modal
  const [editTarget, setEditTarget] = useState<ApiKey | null>(null)
  const [editForm, setEditForm] = useState({ label: "", base_url: "", api_key: "", model_name: "" })
  const [editTest, setEditTest] = useState<TestState>(defaultTest())
  const [editSaving, setEditSaving] = useState(false)

  useEffect(() => {
    api.apiKeys.list().then(setKeys).catch(console.error)
  }, [])

  // ── Add ────────────────────────────────────────────────────────────────────

  const handleTestAdd = async () => {
    if (!form.base_url) return
    setAddTest({ ...defaultTest(), status: "testing" })
    const result = await api.apiKeys.testConnection(form.base_url, form.api_key)
    setAddTest({ status: result.ok ? "ok" : "error", latency_ms: result.latency_ms, models: result.models, error: result.error })
    if (result.ok && result.models.length > 0 && !form.model_name)
      setForm((f) => ({ ...f, model_name: result.models[0] }))
  }

  const handleAdd = async () => {
    if (!form.label || !form.base_url) return
    setAdding(true)
    try {
      const created = await api.apiKeys.create({
        label: form.label,
        type: form.type,
        base_url: form.base_url,
        api_key: form.api_key,
        model_name: form.model_name,
      })
      setKeys((prev) => [created, ...prev])
      setForm(emptyForm())
      setAddTest(defaultTest())
    } finally {
      setAdding(false)
    }
  }

  // ── Delete ─────────────────────────────────────────────────────────────────

  const handleDelete = async () => {
    if (!deleteTarget) return
    await api.apiKeys.delete(deleteTarget.id)
    setKeys((prev) => prev.filter((k) => k.id !== deleteTarget.id))
    setDeleteTarget(null)
  }

  // ── Activate ───────────────────────────────────────────────────────────────

  const handleActivate = async (key: ApiKey) => {
    await api.apiKeys.activate(key.id)
    // Update local state: deactivate same type, activate this one
    setKeys((prev) => prev.map((k) => ({ ...k, is_active: k.type === key.type ? k.id === key.id : k.is_active })))
  }

  // ── Test row ───────────────────────────────────────────────────────────────

  const handleTestRow = async (key: ApiKey) => {
    setRowTest((prev) => ({ ...prev, [key.id]: { ...defaultTest(), status: "testing" } }))
    const result = await api.apiKeys.test(key.id)
    setRowTest((prev) => ({ ...prev, [key.id]: { status: result.ok ? "ok" : "error", latency_ms: result.latency_ms, models: result.models, error: result.error } }))
  }

  // ── Edit ───────────────────────────────────────────────────────────────────

  const openEdit = (key: ApiKey) => {
    setEditTarget(key)
    setEditForm({ label: key.label, base_url: "", api_key: "", model_name: key.model_name })
    setEditTest(defaultTest())
  }

  const handleTestEdit = async () => {
    if (!editForm.base_url) return
    setEditTest({ ...defaultTest(), status: "testing" })
    const result = await api.apiKeys.testConnection(editForm.base_url, editForm.api_key)
    setEditTest({ status: result.ok ? "ok" : "error", latency_ms: result.latency_ms, models: result.models, error: result.error })
    if (result.ok && result.models.length > 0 && !editForm.model_name)
      setEditForm((f) => ({ ...f, model_name: result.models[0] }))
  }

  const handleSaveEdit = async () => {
    if (!editTarget) return
    setEditSaving(true)
    try {
      const patch: Record<string, string> = {}
      if (editForm.label) patch.label = editForm.label
      if (editForm.base_url) patch.base_url = editForm.base_url
      if (editForm.api_key) patch.api_key = editForm.api_key
      if (editForm.model_name) patch.model_name = editForm.model_name
      const updated = await api.apiKeys.update(editTarget.id, patch)
      setKeys((prev) => prev.map((k) => (k.id === editTarget.id ? updated : k)))
      setEditTarget(null)
    } finally {
      setEditSaving(false)
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  const ocrKeys = keys.filter((k) => k.type === "ocr")
  const llmKeys = keys.filter((k) => k.type === "llm")

  return (
    <div className="flex flex-col gap-8 p-6 max-w-3xl">
      <div>
        <h1 className="text-lg font-semibold">Model Configuration</h1>
        <p className="text-xs text-muted-foreground mt-0.5">Add your OCR and LLM endpoints. Set one of each as active for the pipeline.</p>
      </div>

      {/* ── Add form ─────────────────────────────────────────────────────── */}
      <div className="border rounded-lg p-4 bg-muted/20 space-y-3">
        <p className="text-sm font-medium">Add Model Config</p>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label className="text-xs">Label</Label>
            <Input placeholder="My OCR Server" value={form.label} onChange={(e) => setForm((f) => ({ ...f, label: e.target.value }))} />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Type</Label>
            <select
              className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm"
              value={form.type}
              onChange={(e) => setForm((f) => ({ ...f, type: e.target.value as "ocr" | "llm" }))}
            >
              <option value="ocr">OCR</option>
              <option value="llm">LLM</option>
            </select>
          </div>
          <div className="space-y-1 col-span-2">
            <Label className="text-xs">Base URL</Label>
            <div className="flex gap-1.5">
              <Input
                placeholder="http://server/v1"
                value={form.base_url}
                onChange={(e) => { setForm((f) => ({ ...f, base_url: e.target.value })); setAddTest(defaultTest()) }}
              />
              <Button
                variant="outline" size="sm" className="h-9 px-3 shrink-0 gap-1.5"
                onClick={handleTestAdd}
                disabled={!form.base_url || addTest.status === "testing"}
              >
                {addTest.status === "testing" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> :
                  addTest.status === "ok" ? <Wifi className="h-3.5 w-3.5 text-green-600" /> :
                  addTest.status === "error" ? <WifiOff className="h-3.5 w-3.5 text-destructive" /> :
                  <Wifi className="h-3.5 w-3.5" />}
                Test
              </Button>
            </div>
            {addTest.status !== "idle" && <div className="mt-0.5"><TestBadge state={addTest} /></div>}
          </div>
          <div className="space-y-1">
            <Label className="text-xs">API Key <span className="text-muted-foreground">(optional)</span></Label>
            <Input type="password" placeholder="sk-…" value={form.api_key} onChange={(e) => setForm((f) => ({ ...f, api_key: e.target.value }))} />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Model Name</Label>
            <ModelSelect
              models={addTest.models}
              value={form.model_name}
              onChange={(v) => setForm((f) => ({ ...f, model_name: v }))}
              placeholder="model-name"
            />
          </div>
        </div>
        <div className="flex justify-end">
          <Button size="sm" onClick={handleAdd} disabled={adding || !form.label || !form.base_url} className="gap-2">
            <Plus className="h-4 w-4" />
            {adding ? "Adding…" : "Add"}
          </Button>
        </div>
      </div>

      {/* ── OCR configs ──────────────────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold mb-2">OCR Models</h2>
        {ocrKeys.length === 0 ? (
          <p className="text-xs text-muted-foreground py-3 text-center">No OCR models configured</p>
        ) : (
          <KeyTable keys={ocrKeys} rowTest={rowTest} onTest={handleTestRow} onActivate={handleActivate} onEdit={openEdit} onDelete={setDeleteTarget} />
        )}
      </section>

      {/* ── LLM configs ──────────────────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold mb-2">LLM Models</h2>
        {llmKeys.length === 0 ? (
          <p className="text-xs text-muted-foreground py-3 text-center">No LLM models configured</p>
        ) : (
          <KeyTable keys={llmKeys} rowTest={rowTest} onTest={handleTestRow} onActivate={handleActivate} onEdit={openEdit} onDelete={setDeleteTarget} />
        )}
      </section>

      {/* ── Edit dialog ───────────────────────────────────────────────────── */}
      <Dialog open={!!editTarget} onOpenChange={(o) => !o && setEditTarget(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Edit — {editTarget?.label}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-3 py-2">
            <div className="space-y-1">
              <Label className="text-xs">Label</Label>
              <Input value={editForm.label} onChange={(e) => setEditForm((f) => ({ ...f, label: e.target.value }))} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Base URL <span className="text-muted-foreground">(leave blank to keep current)</span></Label>
              <div className="flex gap-1.5">
                <Input
                  placeholder="http://server/v1"
                  value={editForm.base_url}
                  onChange={(e) => { setEditForm((f) => ({ ...f, base_url: e.target.value })); setEditTest(defaultTest()) }}
                />
                <Button variant="outline" size="sm" className="h-9 px-3 shrink-0" onClick={handleTestEdit} disabled={!editForm.base_url || editTest.status === "testing"}>
                  {editTest.status === "testing" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> :
                    editTest.status === "ok" ? <Wifi className="h-3.5 w-3.5 text-green-600" /> :
                    <Wifi className="h-3.5 w-3.5" />}
                </Button>
              </div>
              {editTest.status !== "idle" && <TestBadge state={editTest} />}
            </div>
            <div className="space-y-1">
              <Label className="text-xs">API Key <span className="text-muted-foreground">(leave blank to keep current)</span></Label>
              <Input type="password" placeholder="sk-…" value={editForm.api_key} onChange={(e) => setEditForm((f) => ({ ...f, api_key: e.target.value }))} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Model Name</Label>
              <ModelSelect
                models={editTest.models}
                value={editForm.model_name}
                onChange={(v) => setEditForm((f) => ({ ...f, model_name: v }))}
                placeholder="model-name"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setEditTarget(null)}>Cancel</Button>
            <Button size="sm" onClick={handleSaveEdit} disabled={editSaving}>{editSaving ? "Saving…" : "Save"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Delete confirm ────────────────────────────────────────────────── */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete config?</AlertDialogTitle>
            <AlertDialogDescription><strong>{deleteTarget?.label}</strong> will be permanently deleted.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

// ── KeyTable sub-component ────────────────────────────────────────────────────

function KeyTable({
  keys,
  rowTest,
  onTest,
  onActivate,
  onEdit,
  onDelete,
}: {
  keys: ApiKey[]
  rowTest: Record<number, TestState>
  onTest: (k: ApiKey) => void
  onActivate: (k: ApiKey) => void
  onEdit: (k: ApiKey) => void
  onDelete: (k: ApiKey) => void
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Label</TableHead>
          <TableHead>Model</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right w-[180px]">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {keys.map((k) => {
          const ts = rowTest[k.id] ?? { status: "idle" } as TestState
          return (
            <TableRow key={k.id}>
              <TableCell className="font-medium">
                <div className="flex items-center gap-2">
                  {k.label}
                  {k.is_active && <Badge variant="default" className="text-[10px] h-4 px-1.5">Active</Badge>}
                </div>
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">{k.model_name || "—"}</TableCell>
              <TableCell>
                {ts.status === "testing" && <span className="flex items-center gap-1 text-xs text-muted-foreground"><Loader2 className="h-3 w-3 animate-spin" />Testing…</span>}
                {ts.status === "ok" && <span className="flex items-center gap-1.5 text-xs text-green-600"><CheckCircle2 className="h-3 w-3" />{ts.latency_ms}ms</span>}
                {ts.status === "error" && <span className="flex items-center gap-1.5 text-xs text-destructive"><XCircle className="h-3 w-3" />Failed</span>}
              </TableCell>
              <TableCell>
                <div className="flex items-center justify-end gap-1">
                  <Button
                    variant="ghost" size="sm" className="h-7 px-2 text-xs gap-1"
                    onClick={() => onTest(k)}
                    disabled={ts.status === "testing"}
                    title="Test connection"
                  >
                    <Wifi className="h-3.5 w-3.5" />
                    Test
                  </Button>
                  {!k.is_active && (
                    <Button
                      variant="outline" size="sm" className="h-7 px-2 text-xs"
                      onClick={() => onActivate(k)}
                      title="Set as active"
                    >
                      Set Active
                    </Button>
                  )}
                  <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => onEdit(k)} title="Edit">
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                  <Button variant="ghost" size="sm" className="h-7 w-7 p-0 text-destructive hover:text-destructive" onClick={() => onDelete(k)} title="Delete">
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}
