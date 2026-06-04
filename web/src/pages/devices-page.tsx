import { useEffect, useState, useCallback } from "react"
import { Wifi, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { api } from "@/api/client"
import type { Device } from "@/types"

function secondsAgo(iso?: string): string {
  if (!iso) return ""
  const then = new Date(iso).getTime()
  const s = Math.max(0, Math.round((Date.now() - then) / 1000))
  return s < 60 ? `${s}s ago` : `${Math.round(s / 60)}m ago`
}

export function DevicesPage() {
  const [devices, setDevices] = useState<Device[]>([])
  const [loading, setLoading] = useState(true)

  const scan = useCallback(() => {
    api.devices.list()
      .then(setDevices)
      .catch(() => setDevices([]))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    scan()
    const t = setInterval(scan, 3000)
    return () => clearInterval(t)
  }, [scan])

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-lg font-semibold flex items-center gap-2">
          <Wifi className="h-5 w-5" /> Devices
        </h1>
        <Button size="sm" variant="outline" onClick={scan}>
          <RefreshCw className="h-4 w-4 mr-1.5" /> Scan
        </Button>
      </div>

      {loading ? (
        <p className="text-sm text-muted-foreground">Scanning…</p>
      ) : devices.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 py-16 text-muted-foreground">
          <Wifi className="h-10 w-10" />
          <p className="text-sm">No devices online — flash a mic and it'll appear here.</p>
        </div>
      ) : (
        <ul className="divide-y rounded-lg border">
          {devices.map((d) => (
            <li key={d.device_id} className="flex items-center justify-between px-4 py-3">
              <div className="flex items-center gap-3 min-w-0">
                <span className="h-2.5 w-2.5 rounded-full bg-green-500 shrink-0" />
                <div className="min-w-0">
                  <p className="font-medium truncate">{d.name}</p>
                  <p className="text-xs text-muted-foreground truncate">{d.device_id}</p>
                </div>
              </div>
              <span className="text-xs text-muted-foreground shrink-0">
                seen {secondsAgo(d.last_seen)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
