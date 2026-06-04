# ESP32 Discovery + Server Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flash one shared firmware to any ESP32 and have it auto-connect to the cloud-hosted server, appear in a live "Devices" list on the web, with the whole stack running on the 4090 box.

**Architecture:** Each ESP32 derives a stable `device_id` from its MAC and sends it in a `hello` WS message to a hardcoded public server host. The backend keeps a Redis registry of online devices (TTL heartbeat) exposed via `GET /api/devices`. A web "Devices" page polls that endpoint. The full stack runs on the 4090 via docker-compose; STT stays native at `localhost:2109`.

**Tech Stack:** ESP32 Arduino (PlatformIO, WebSocketsClient) · FastAPI · Redis · React + TypeScript + Vite · Docker Compose

**Note on testing:** This repo has no unit-test harness (no `tests/` dir; pytest listed but unused). Following the existing repo convention (see `docs/superpowers/plans/2026-04-19-multi-user-multi-mic-sessions.md`), verification is integration-style: `redis-cli`, `curl`, browser, and ESP32 serial. Each task includes explicit verification commands with expected output.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `api/redis_client.py` | Device registry: register/touch/unregister/list with TTL heartbeat |
| Modify | `api/main.py` | Wire registry into `/ws` (hello, heartbeat, disconnect) |
| Create | `api/routes/devices.py` | `GET /api/devices` endpoint |
| Modify | `api/main.py` | Register devices router |
| Modify | `web/src/types/index.ts` | `Device` type |
| Modify | `web/src/api/client.ts` | `api.devices.list()` |
| Create | `web/src/pages/devices-page.tsx` | Devices/Scan page |
| Modify | `web/src/components/app-sidebar.tsx` | "Devices" sidebar entry + `activePage` union |
| Modify | `web/src/App.tsx` | `/devices` route, render page, sidebar wiring |
| Modify | `PlatformIO/Projects/NLP/src/main.cpp` | MAC device_id, hello, hardcoded host, drop mDNS/halt |
| Create | `deploy/nginx.conf` | Reverse proxy: single public port → backend + frontend |
| Modify | `docker-compose.yml` | Add nginx (publishes 2108); backend/frontend internal-only; STT via host.docker.internal:2109 |

---

## Task 1: Backend device registry (Redis)

**Files:**
- Modify: `api/redis_client.py`

- [ ] **Step 1: Add registry functions to `api/redis_client.py`**

Append at the end of the file (after `get_connected_devices`):

```python
# ── Device registry (live, TTL-based heartbeat) ───────────────────
DEVICE_TTL = 30          # seconds; refreshed on hello + each heartbeat
ONLINE_SET = "online_devices"


def register_device(device_id: str, name: str = "", ip: str = "") -> None:
    """Mark a device online with metadata; (re)set its TTL."""
    r = get_redis()
    now = datetime.now(TZ_VN).isoformat()
    key = f"device:{device_id}"
    r.hset(key, mapping={
        "device_id": device_id,
        "name": name or device_id,
        "ip": ip,
        "connected_at": now,
        "last_seen": now,
    })
    r.expire(key, DEVICE_TTL)
    r.sadd(ONLINE_SET, device_id)


def touch_device(device_id: str) -> None:
    """Heartbeat: refresh last_seen + TTL if the device is still registered."""
    r = get_redis()
    key = f"device:{device_id}"
    if r.exists(key):
        r.hset(key, "last_seen", datetime.now(TZ_VN).isoformat())
        r.expire(key, DEVICE_TTL)


def unregister_device(device_id: str) -> None:
    """Remove a device from the online registry (on disconnect)."""
    r = get_redis()
    r.delete(f"device:{device_id}")
    r.srem(ONLINE_SET, device_id)


def get_online_devices() -> list[dict]:
    """Return metadata for devices whose TTL hash is still alive; prune the rest."""
    r = get_redis()
    out = []
    for device_id in r.smembers(ONLINE_SET):
        meta = r.hgetall(f"device:{device_id}")
        if meta:
            out.append(meta)
        else:
            r.srem(ONLINE_SET, device_id)   # TTL expired → prune stale id
    return sorted(out, key=lambda d: d.get("connected_at", ""))
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `cd /Users/tuantran/WorkSpace/process_documents && python -c "import api.redis_client as rc; print([f for f in ('register_device','touch_device','unregister_device','get_online_devices') if hasattr(rc,f)])"`
Expected: `['register_device', 'touch_device', 'unregister_device', 'get_online_devices']`

- [ ] **Step 3: Commit**

```bash
git add api/redis_client.py
git commit -m "feat: add live device registry (register/touch/unregister/list) in redis_client"
```

---

## Task 2: Wire registry into the WebSocket handler

**Files:**
- Modify: `api/main.py`

- [ ] **Step 1: Import the registry functions in `api/main.py`**

Find this import (line 23):

```python
from api.redis_client import get_redis
```

Replace with:

```python
from api.redis_client import get_redis, register_device, touch_device, unregister_device
```

- [ ] **Step 2: Replace the hello-branch registration in `websocket_root`**

In `api/main.py`, find (inside the hello handling, ~lines 210-220):

```python
                    if payload.get("type") == "hello":
                        device_id = payload.get("device_id", f"esp32-{id(websocket) % 10000:04d}")
                        await websocket.send_text(json.dumps({
                            "type": "hello_ack",
                            "device_id": device_id,
                            "status": "ok",
                        }))
                        logger.info(f"ESP32 identified: {device_id}")
                        r = get_redis()
                        r.sadd("connected_devices", device_id)
                        continue
```

Replace with:

```python
                    if payload.get("type") == "hello":
                        device_id = payload.get("device_id", f"esp32-{id(websocket) % 10000:04d}")
                        name = payload.get("name", device_id)
                        await websocket.send_text(json.dumps({
                            "type": "hello_ack",
                            "device_id": device_id,
                            "status": "ok",
                        }))
                        ip = websocket.client.host if websocket.client else ""
                        logger.info(f"ESP32 identified: {device_id} ({name}) from {ip}")
                        register_device(device_id, name, ip)
                        continue
```

- [ ] **Step 3: Replace the auto-assign (binary-before-hello) registration**

Find (~lines 227-231):

```python
            if device_id is None:
                device_id = f"esp32-{id(websocket) % 10000:04d}"
                logger.info(f"ESP32 auto-assigned: {device_id}")
                r = get_redis()
                r.sadd("connected_devices", device_id)
```

Replace with:

```python
            if device_id is None:
                device_id = f"esp32-{id(websocket) % 10000:04d}"
                logger.info(f"ESP32 auto-assigned: {device_id}")
                ip = websocket.client.host if websocket.client else ""
                register_device(device_id, device_id, ip)
```

- [ ] **Step 4: Add a heartbeat in the audio loop**

Find the 0.5s SSE block (~lines 241-247) ending with `save_audio_level(device_id, avg_amp, avg_peak)`:

```python
                save_audio_level(device_id, avg_amp, avg_peak)
```

Add `touch_device(device_id)` immediately after it:

```python
                save_audio_level(device_id, avg_amp, avg_peak)
                touch_device(device_id)
```

- [ ] **Step 5: Replace the disconnect cleanup**

Find the `finally` block (~lines 268-274):

```python
    finally:
        if device_id:
            logger.info(f"ESP32 disconnected: {device_id}")
            r = get_redis()
            r.srem("connected_devices", device_id)
        else:
            logger.info("ESP32 disconnected (never identified)")
```

Replace with:

```python
    finally:
        if device_id:
            logger.info(f"ESP32 disconnected: {device_id}")
            unregister_device(device_id)
        else:
            logger.info("ESP32 disconnected (never identified)")
```

- [ ] **Step 6: Verify import + app loads**

Run: `cd /Users/tuantran/WorkSpace/process_documents && python -c "import api.main; print('main imports OK')"`
Expected: `main imports OK` (no ImportError).

- [ ] **Step 7: Commit**

```bash
git add api/main.py
git commit -m "feat: wire device registry into /ws (hello, heartbeat, disconnect)"
```

---

## Task 3: `GET /api/devices` endpoint

**Files:**
- Create: `api/routes/devices.py`
- Modify: `api/main.py`

- [ ] **Step 1: Create `api/routes/devices.py`**

```python
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from api.redis_client import get_online_devices

router = APIRouter(prefix="/api", tags=["devices"])


class DeviceOut(BaseModel):
    device_id: str
    name: str
    connected_at: Optional[str] = None
    last_seen: Optional[str] = None
    ip: Optional[str] = None


@router.get("/devices", response_model=list[DeviceOut])
def list_devices():
    """List ESP32 devices currently online (live Redis registry)."""
    return get_online_devices()
```

- [ ] **Step 2: Register the router in `api/main.py`**

Find the import block (~line 27):

```python
from api.routes.auth import router as auth_router
```

Add after it:

```python
from api.routes.devices import router as devices_router
```

Find the router includes (~line 167):

```python
app.include_router(auth_router)
```

Add after it:

```python
app.include_router(devices_router)
```

- [ ] **Step 3: Verify endpoint registered**

Run: `cd /Users/tuantran/WorkSpace/process_documents && python -c "import api.main as m; print('/api/devices' in [r.path for r in m.app.routes])"`
Expected: `True`

- [ ] **Step 4: Commit**

```bash
git add api/routes/devices.py api/main.py
git commit -m "feat: add GET /api/devices endpoint listing online ESP32 devices"
```

---

## Task 4: Frontend types + API client

**Files:**
- Modify: `web/src/types/index.ts`
- Modify: `web/src/api/client.ts`

- [ ] **Step 1: Add the `Device` type to `web/src/types/index.ts`**

Append at the end of the file:

```typescript
export interface Device {
  device_id: string
  name: string
  connected_at?: string
  last_seen?: string
  ip?: string
}
```

- [ ] **Step 2: Import the type in `web/src/api/client.ts`**

In the first line's import list, add `Device`:

```typescript
import type { Chunk, DocImage, Document, Workspace, Formula, OcrPageData, ApiKey, SearchResult, RecordingSession, SessionRagBlock, SessionParticipant, User, GraphNode, Device } from "@/types"
```

- [ ] **Step 3: Add the `devices` API group**

In `web/src/api/client.ts`, find the closing of the `sessions:` group and the final `}` of the `api` object (the `participants:` line near the end):

```typescript
    participants: (id: number) =>
      request<SessionParticipant[]>(`/api/sessions/${id}/participants`),
  },
}
```

Replace with:

```typescript
    participants: (id: number) =>
      request<SessionParticipant[]>(`/api/sessions/${id}/participants`),
  },

  devices: {
    list: () => request<Device[]>("/api/devices"),
  },
}
```

- [ ] **Step 4: Verify the web type-checks**

Run: `cd /Users/tuantran/WorkSpace/process_documents/web && npx tsc --noEmit 2>&1 | head -5`
Expected: no errors referencing `Device` or `client.ts` (pre-existing unrelated errors, if any, are fine).

- [ ] **Step 5: Commit**

```bash
git add web/src/types/index.ts web/src/api/client.ts
git commit -m "feat: add Device type and api.devices.list() client method"
```

---

## Task 5: Devices page + sidebar + route

**Files:**
- Create: `web/src/pages/devices-page.tsx`
- Modify: `web/src/components/app-sidebar.tsx`
- Modify: `web/src/App.tsx`

- [ ] **Step 1: Create `web/src/pages/devices-page.tsx`**

```tsx
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
```

- [ ] **Step 2: Add a "Devices" entry to `web/src/components/app-sidebar.tsx`**

In the icon import block (lines 2-12), add `Wifi`:

```tsx
import {
  Database,
  FolderOpen,
  BookOpen,
  ChevronRight,
  Plus,
  Activity,
  Settings,
  Radio,
  LogOut,
  Wifi,
} from "lucide-react";
```

Update the `activePage` prop union (line 33):

```tsx
  activePage: "dataset" | "workspace" | "realtime" | "sessions" | "settings" | "devices" | null;
```

Add `onSelectDevices` to the props interface (after `onSelectSettings` on line 43):

```tsx
  onSelectSettings: () => void;
  onSelectDevices: () => void;
```

Add `onSelectDevices` to the destructured params (after `onSelectSettings` ~line 55):

```tsx
  onSelectSettings,
  onSelectDevices,
```

Add the sidebar group after the Real-time Monitor group (after its closing `</SidebarGroup>` ~line 115):

```tsx
        {/* Devices */}
        <SidebarGroup>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                isActive={activePage === "devices"}
                onClick={onSelectDevices}
                className="cursor-pointer"
              >
                <Wifi className="size-4" />
                <span>Devices</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroup>
```

- [ ] **Step 3: Wire the route into `web/src/App.tsx`**

Add the page import after the other page imports (after `import { LoginPage } ...`):

```tsx
import { DevicesPage } from "@/pages/devices-page";
```

Add the path flag near the other `isX` flags (after `isSessions` ~line 57):

```tsx
  const isDevices = location.pathname === "/devices";
```

In the `<AppSidebar>` JSX, update `activePage` to include devices and add the handler. Find:

```tsx
            activePage={
              isRealtime ? "realtime"
              : isSettings ? "settings"
              : isDataset ? "dataset"
              : isWorkspace ? "workspace"
              : isSessions ? "sessions"
              : null
            }
```

Replace with:

```tsx
            activePage={
              isRealtime ? "realtime"
              : isSettings ? "settings"
              : isDataset ? "dataset"
              : isWorkspace ? "workspace"
              : isSessions ? "sessions"
              : isDevices ? "devices"
              : null
            }
```

Find `onSelectSettings={() => navigate("/settings")}` and add after it:

```tsx
            onSelectSettings={() => navigate("/settings")}
            onSelectDevices={() => navigate("/devices")}
```

Add the render branch. Find the main content conditional chain that begins `{isSettings ? (` and add a Devices branch at the top of the chain:

```tsx
              {isDevices ? (
                <div className="flex-1 overflow-y-auto">
                  <DevicesPage />
                </div>
              ) : isSettings ? (
```

(The existing `{isSettings ? (` becomes the `: isSettings ? (` continuation — i.e. prepend the `isDevices` branch before it.)

Add the route in the `<Routes>` block (after the `/settings` route):

```tsx
          <Route path="/devices" element={<AuthGuard><AppContent /></AuthGuard>} />
```

- [ ] **Step 4: Verify build**

Run: `cd /Users/tuantran/WorkSpace/process_documents/web && npx tsc --noEmit 2>&1 | head -8`
Expected: no new errors in `devices-page.tsx`, `app-sidebar.tsx`, or `App.tsx`.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/devices-page.tsx web/src/components/app-sidebar.tsx web/src/App.tsx
git commit -m "feat: add Devices page with live scan + sidebar entry + route"
```

---

## Task 6: Firmware — shared, MAC-based identity, hardcoded host, no mDNS/halt

**Files:**
- Modify: `PlatformIO/Projects/NLP/src/main.cpp` (absolute: `/Users/tuantran/Documents/PlatformIO/Projects/NLP/src/main.cpp`)

- [ ] **Step 1: Replace the server config + add identity globals**

Find (lines 16-21):

```cpp
// ============================================================
//  CẤU HÌNH WEBSOCKET SERVER
// ============================================================
const char* wsHostname = "process-docs";  // mDNS hostname (queryHost adds .local)
const int   wsPort     = 8000;
char        wsResolvedIP[16] = "";               // filled after mDNS resolve
```

Replace with:

```cpp
// ============================================================
//  CẤU HÌNH WEBSOCKET SERVER (public cloud host — no mDNS)
// ============================================================
#define SERVER_HOST "49.213.89.44"   // 4090 server public IP
#define SERVER_PORT 2108             // backend WS/API port
const char* wsPath = "/ws";

// Device identity — derived from MAC at boot (shared firmware, unique per chip)
String deviceId   = "esp32-unknown";
String deviceName = "ESP32";
```

- [ ] **Step 2: Send `hello` on WS connect**

Find the `WStype_CONNECTED` case (lines 91-94):

```cpp
    case WStype_CONNECTED:
      Serial.println("WebSocket connected");
      disconnectCount = 0;
      break;
```

Replace with:

```cpp
    case WStype_CONNECTED: {
      Serial.println("WebSocket connected");
      disconnectCount = 0;
      String hello = String("{\"type\":\"hello\",\"device_id\":\"") +
                     deviceId + "\",\"name\":\"" + deviceName + "\"}";
      webSocket.sendTXT(hello);
      Serial.println("Sent hello: " + hello);
      break;
    }
```

- [ ] **Step 3: Delete the mDNS refresh function and its trigger**

Delete the entire `refreshMDNS()` function (lines 54-76) and the `#define MDNS_REFRESH_AFTER 5` line (line 52).

In the `WStype_DISCONNECTED` case, replace (lines 83-90):

```cpp
    case WStype_DISCONNECTED:
      Serial.println("WebSocket disconnected");
      disconnectCount++;
      if (disconnectCount >= MDNS_REFRESH_AFTER) {
        disconnectCount = 0;
        refreshMDNS();
      }
      break;
```

with:

```cpp
    case WStype_DISCONNECTED:
      Serial.println("WebSocket disconnected (auto-reconnect in 5s)");
      disconnectCount++;
      break;
```

- [ ] **Step 4: Derive device identity after WiFi connects + replace mDNS block**

Find (lines 222-242), from the "Connected! IP" line through the mDNS resolve block:

```cpp
  Serial.println("Connected! IP: " + WiFi.localIP().toString());

  // mDNS resolve
  Serial.print("Resolving process-docs.local via mDNS");
  if (!MDNS.begin("esp32")) {
    Serial.println("\nWarning: MDNS.begin failed");
  }
  IPAddress serverIP;
  int mdnsRetry = 0;
  while (mdnsRetry < 20) {
    serverIP = MDNS.queryHost(wsHostname, 2000);
    if (serverIP != INADDR_NONE) break;
    Serial.print(".");
    mdnsRetry++;
  }
  if (serverIP == INADDR_NONE) {
    Serial.println("\nmDNS resolve failed — check server is running. Halting.");
    while(1) delay(1000);
  }
  serverIP.toString().toCharArray(wsResolvedIP, sizeof(wsResolvedIP));
  Serial.printf("\nResolved: %s → %s\n", wsHostname, wsResolvedIP);
```

Replace with:

```cpp
  Serial.println("Connected! IP: " + WiFi.localIP().toString());

  // Derive stable device id from MAC (last 6 hex), e.g. B0:CB:D8:CF:39:24 -> esp32-CF3924
  String mac = WiFi.macAddress();      // "B0:CB:D8:CF:39:24"
  mac.replace(":", "");                 // "B0CBD8CF3924"
  String suffix = mac.substring(mac.length() - 6);   // "CF3924"
  deviceId   = "esp32-" + suffix;
  deviceName = "ESP32 " + suffix;
  Serial.println("Device ID: " + deviceId);
  Serial.printf("Server: %s:%d%s\n", SERVER_HOST, SERVER_PORT, wsPath);
```

- [ ] **Step 5: Point WebSocket at the hardcoded host**

Find (line 267):

```cpp
  // WebSocket
  webSocket.begin(wsResolvedIP, wsPort, "/ws");
```

Replace with:

```cpp
  // WebSocket — direct to public host, library auto-reconnects every 5s
  webSocket.begin(SERVER_HOST, SERVER_PORT, wsPath);
```

- [ ] **Step 6: Remove the now-unused mDNS include**

Find (line 4):

```cpp
#include <ESPmDNS.h>
```

Delete it.

- [ ] **Step 7: Compile (no upload) to verify it builds**

Run: `cd /Users/tuantran/Documents/PlatformIO/Projects/NLP && /opt/homebrew/bin/pio run 2>&1 | tail -5`
Expected: `SUCCESS` (build finishes without errors; no references to `MDNS`, `refreshMDNS`, `wsResolvedIP`, or `wsHostname`).

- [ ] **Step 8: Commit (firmware repo)**

```bash
cd /Users/tuantran/Documents/PlatformIO/Projects/NLP
git add src/main.cpp
git commit -m "feat: MAC-based device_id + hello + hardcoded cloud host, drop mDNS/halt"
```

---

## Task 7: Deploy the stack to the 4090 (single public port via nginx)

**Files:**
- Create: `deploy/nginx.conf`
- Modify: `docker-compose.yml`

The 4090 runs STT natively on `:2109`. We deploy db + redis + backend + frontend on the **internal** Docker network (no public ports) and add one `nginx` reverse proxy as the **only** public entrypoint on `2108`. Backend reaches the native STT through the Docker host gateway.

- [ ] **Step 1: Create `deploy/nginx.conf`**

```nginx
events {}

http {
  # Backend API + WebSocket
  upstream backend  { server backend:8000; }
  # Vite dev frontend
  upstream frontend { server frontend:5173; }

  map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
  }

  server {
    listen 80;

    # REST API
    location /api/ {
      proxy_pass http://backend;
      proxy_set_header Host $host;
      proxy_set_header X-Real-IP $remote_addr;
    }

    # ESP32 audio + browser monitor WebSockets
    location /ws {
      proxy_pass http://backend;
      proxy_http_version 1.1;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection $connection_upgrade;
      proxy_set_header Host $host;
      proxy_read_timeout 1h;
    }

    # Everything else → frontend (includes vite HMR websocket)
    location / {
      proxy_pass http://frontend;
      proxy_http_version 1.1;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection $connection_upgrade;
      proxy_set_header Host $host;
    }
  }
}
```

Note: `location /ws` matches both `/ws` and `/ws/audio-monitor` (prefix match).

- [ ] **Step 2: Make backend internal-only + point STT at the host gateway**

In `docker-compose.yml`, in the `backend` service: set the STT URL, add `extra_hosts`, and **remove** the `ports:` block (so it is reachable only inside the compose network). The backend `environment`, `extra_hosts`, `volumes`, and `command` should read:

```yaml
    environment:
      DATABASE_URL: postgresql://postgres:postgres@db:5432/pdf_processor
      REDIS_URL: redis://redis:6379
      EMBEDDING_SERVICE_URL: http://host.docker.internal:8001
      WHISPER_SERVICE_URL: http://host.docker.internal:2109
      PYTHONUNBUFFERED: "1"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - ./api:/app/api
      - ./data:/app/data
    command: uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

(There must be no `ports:` key under `backend` after this edit.)

- [ ] **Step 3: Make frontend internal-only**

In the `frontend` service, **remove** its `ports:` block (the `- "5173:5173"` mapping). Leave `VITE_PROXY_TARGET: http://pdf-backend:8000` unchanged. The frontend is now reached only through nginx.

- [ ] **Step 4: Add the nginx service to `docker-compose.yml`**

Add this service (alongside `backend`, `frontend`, `db`, `redis`):

```yaml
  nginx:
    image: nginx:1.27-alpine
    container_name: pdf-nginx
    depends_on:
      - backend
      - frontend
    volumes:
      - ./deploy/nginx.conf:/etc/nginx/nginx.conf:ro
    ports:
      - "2108:80"
```

- [ ] **Step 5: Commit the deploy changes**

```bash
cd /Users/tuantran/WorkSpace/process_documents
git add deploy/nginx.conf docker-compose.yml
git commit -m "feat: single public port — nginx reverse proxy on 2108, backend/frontend internal"
```

- [ ] **Step 6: Copy the repo to the 4090**

Run from the Mac:

```bash
ssh Model_Training_Server 'mkdir -p ~/process_documents'
rsync -az --delete \
  --exclude '.git' --exclude 'web/node_modules' --exclude 'data' \
  --exclude 'models' --exclude 'embedder_venv' \
  -e ssh /Users/tuantran/WorkSpace/process_documents/ \
  Model_Training_Server:~/process_documents/
```

Expected: rsync completes with no error.

- [ ] **Step 7: Create the server `.env` on the 4090**

Run:

```bash
ssh Model_Training_Server 'cat > ~/process_documents/.env <<EOF
DATABASE_URL=postgresql://postgres:postgres@db:5432/pdf_processor
REDIS_URL=redis://redis:6379
EMBEDDING_DIM=384
JWT_SECRET_KEY=change-me-in-production
WHISPER_SERVICE_URL=http://host.docker.internal:2109
EOF
echo wrote .env'
```

Expected: `wrote .env`

- [ ] **Step 8: Confirm STT is reachable on the host before starting the stack**

Run: `ssh Model_Training_Server 'curl -s --max-time 5 http://localhost:2109/health'`
Expected: JSON with `"provider":"cuda"`. If empty, the STT service must be started first (see `~/zipformer-asr`).

- [ ] **Step 9: Build + start the stack on the 4090 (db, redis, backend, frontend, nginx — no whisper)**

Run:

```bash
ssh Model_Training_Server 'cd ~/process_documents && docker compose up -d --build db redis backend frontend nginx'
```

Expected: all five containers report `Started`. (First build takes several minutes.)

- [ ] **Step 10: Verify backend health through nginx (single public port)**

Run: `curl -s --max-time 8 http://49.213.89.44:2108/api/health`
Expected: `{"status":"ok"}`

- [ ] **Step 11: Verify the devices endpoint reachable publicly**

Run: `curl -s --max-time 8 http://49.213.89.44:2108/api/devices`
Expected: `[]` (no devices yet) — a valid empty JSON array, not an error.

- [ ] **Step 12: Verify the web loads publicly through the same port**

Run: `curl -s -o /dev/null -w "HTTP %{http_code}\n" --max-time 8 http://49.213.89.44:2108/`
Expected: `HTTP 200`

---

## Task 8: End-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Flash the firmware to a connected ESP32**

Run: `cd /Users/tuantran/Documents/PlatformIO/Projects/NLP && /opt/homebrew/bin/pio run -t upload 2>&1 | tail -8`
Expected: `Hard resetting via RTS pin...` / upload success.

- [ ] **Step 2: Confirm the device boots, identifies, and connects (serial)**

Open serial at 115200 (e.g. `pio device monitor`). Expected lines:
- `Device ID: esp32-XXXXXX`
- `Server: 49.213.89.44:2108/ws`
- `WebSocket connected`
- `Sent hello: {"type":"hello","device_id":"esp32-XXXXXX",...}`

(If WiFi is unconfigured, join AP `ESP32-Audio-Setup` and set WiFi once.)

- [ ] **Step 3: Confirm the device appears in the registry on the server**

Run: `ssh Model_Training_Server 'docker exec pdf-redis redis-cli SMEMBERS online_devices'`
Expected: includes `esp32-XXXXXX`.

- [ ] **Step 4: Confirm `GET /api/devices` lists it publicly**

Run: `curl -s http://49.213.89.44:2108/api/devices`
Expected: a JSON array containing an object with `"device_id":"esp32-XXXXXX"` and `"name":"ESP32 XXXXXX"`.

- [ ] **Step 5: Confirm it shows in the web Devices page**

Open `http://49.213.89.44:2108`, log in, click **Devices** in the sidebar. Expected: the device appears with a green online dot and "seen Ns ago", updating every ~3s.

- [ ] **Step 6: Confirm TTL removal**

Power off the ESP32. Wait ~35s. Re-run Step 4. Expected: the array no longer contains the device (TTL expired + disconnect pruned it).

- [ ] **Step 7: Final commit (if any verification tweaks were made)**

```bash
cd /Users/tuantran/WorkSpace/process_documents
git status   # commit only if files changed during verification
```

---

## Self-review notes

- **Spec coverage:** (A) firmware → Task 6; (B) registry + endpoint → Tasks 1-3; (C) web page → Tasks 4-5; (D) deploy → Task 7; E2E → Task 8. All spec sections covered.
- **Type consistency:** `register_device/touch_device/unregister_device/get_online_devices` defined in Task 1 and used verbatim in Tasks 2-3. Redis keys `device:{id}` + set `online_devices` consistent across functions. Firmware `deviceId`/`deviceName` globals defined in Task 6 Step 1, set in Step 4, used in Step 2. Frontend `Device` type fields match `DeviceOut` (device_id, name, connected_at, last_seen, ip).
- **Ports:** single public port **2108** (nginx) → internal backend:8000 + frontend:5173; STT internal at host:2109. Firmware `SERVER_PORT 2108`, nginx publishes `2108:80`, all verification curls use `49.213.89.44:2108`. Backend/frontend have no published ports.
