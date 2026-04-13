import { useEffect, useState, useCallback } from "react"
import { Plus, Radio, Trash2, Play, Clock, BookOpen } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog"
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select"
import { api } from "@/api/client"
import type { RecordingSession, Workspace } from "@/types"

interface SessionsPageProps {
  workspaces: Workspace[]
  onSelectSession: (session: RecordingSession) => void
}

export function SessionsPage({ workspaces, onSelectSession }: SessionsPageProps) {
  const [sessions, setSessions] = useState<RecordingSession[]>([])
  const [loading, setLoading] = useState(true)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [newName, setNewName] = useState("")
  const [newWsId, setNewWsId] = useState<string>("")
  const [creating, setCreating] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<number | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try { setSessions(await api.sessions.list()) }
    catch (e) { console.error(e) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const handleCreate = async () => {
    if (!newName.trim()) return
    setCreating(true)
    try {
      const ws = newWsId && newWsId !== "none" ? parseInt(newWsId) : null
      const s = await api.sessions.create(newName.trim(), ws)
      setSessions(prev => [s, ...prev])
      setDialogOpen(false)
      setNewName("")
      setNewWsId("")
      onSelectSession(s)
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to create session")
    } finally {
      setCreating(false)
    }
  }

  const handleDeleteConfirm = async () => {
    if (deleteTarget === null) return
    try {
      await api.sessions.delete(deleteTarget)
      setSessions(prev => prev.filter(s => s.id !== deleteTarget))
    } catch (e) {
      console.error("Delete failed:", e)
    } finally {
      setDeleteTarget(null)
    }
  }

  const statusVariant = (s: string) =>
    s === "active" ? "default" : s === "stopped" ? "outline" : "secondary"

  return (
    <div className="flex flex-col h-full p-6 gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <Radio className="h-5 w-5" /> Recording Sessions
        </h2>
        <Button size="sm" onClick={() => setDialogOpen(true)}>
          <Plus className="h-3.5 w-3.5 mr-1" /> New Session
        </Button>
      </div>

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : sessions.length === 0 ? (
        <div className="flex flex-col items-center justify-center flex-1 gap-3 text-muted-foreground">
          <Radio className="h-10 w-10 opacity-30" />
          <p className="text-sm">No sessions yet. Create one to start recording.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {sessions.map(s => (
            <div
              key={s.id}
              className="flex items-center gap-3 p-3 rounded-lg border cursor-pointer hover:bg-muted/50 transition-colors"
              onClick={() => onSelectSession(s)}
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm truncate">{s.name}</span>
                  <Badge variant={statusVariant(s.status) as "default" | "secondary" | "outline"}>
                    {s.status === "active" && <Radio className="h-2.5 w-2.5 mr-1 animate-pulse" />}
                    {s.status}
                  </Badge>
                </div>
                <div className="flex items-center gap-3 mt-0.5 text-xs text-muted-foreground">
                  {s.workspace_name && (
                    <span className="flex items-center gap-1">
                      <BookOpen className="h-3 w-3" /> {s.workspace_name}
                    </span>
                  )}
                  <span className="flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {new Date(s.created_at).toLocaleString()}
                  </span>
                  <span>
                    {s.block_count} block{s.block_count !== 1 ? "s" : ""} ·{" "}
                    {s.transcript_count} transcript{s.transcript_count !== 1 ? "s" : ""}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <Button size="sm" variant="ghost" className="h-7 w-7 p-0"
                  onClick={(e) => { e.stopPropagation(); onSelectSession(s) }}>
                  <Play className="h-3.5 w-3.5" />
                </Button>
                <Button size="sm" variant="ghost"
                  className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                  onClick={(e) => { e.stopPropagation(); setDeleteTarget(s.id) }}>
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <AlertDialog open={deleteTarget !== null} onOpenChange={(o) => { if (!o) setDeleteTarget(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete session?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete the session and all its transcripts. Cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleDeleteConfirm} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New Recording Session</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-3 py-2">
            <Input
              placeholder="Session name (e.g. Meeting 2026-04-11)"
              value={newName}
              onChange={e => setNewName(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleCreate()}
              autoFocus
            />
            <Select value={newWsId} onValueChange={setNewWsId}>
              <SelectTrigger>
                <SelectValue placeholder="Select workspace (optional)" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">No workspace</SelectItem>
                {workspaces.map(ws => (
                  <SelectItem key={ws.id} value={String(ws.id)}>{ws.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={creating || !newName.trim()}>
              {creating ? "Creating…" : "Create & Open"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
