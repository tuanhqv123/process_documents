# ESP32 Device Discovery + Server Deploy — Design

**Date:** 2026-06-04
**Status:** Approved (scope), pending implementation plan

## Goal

Two outcomes, in priority order:

1. **Upload-and-connect firmware** — flash the *same* firmware to any ESP32; with no per-device configuration it auto-connects to the cloud server and shows up in the web. The only per-site step is entering WiFi once (existing WiFiManager portal).
2. **Discovery** — the web has a screen that scans/lists the ESP32 devices currently online, so a user can see "the mics around".
3. **Server deploy** — host the whole stack (backend + DB + Redis + web) on the existing 4090 box so devices anywhere on the internet can connect.

Out of scope for now (deferred): public rooms, assigning a mic to a specific room, multi-user room sharing, TLS/WSS, auth on the discovery screen. The existing invite-code session sharing stays as-is and is not extended here.

## Current state

- Single-device local setup works: ESP32 → mDNS `process-docs.local` → backend `/ws` (Docker, port 8000) → remote Zipformer STT (`49.213.89.44:2109`).
- Backend `/ws` handler (`api/main.py`) already accepts a `hello` message with `device_id` and does `r.sadd("connected_devices", device_id)` — but never removes on disconnect and stores no metadata.
- Firmware (`PlatformIO/Projects/NLP/src/main.cpp`) does **not** send `hello`/`device_id`; it resolves the server via mDNS and streams raw PCM. mDNS only works on the LAN.
- 4090 server: Ubuntu 24.04, Docker + nvidia-container-toolkit, cloud security group opens TCP **2100–2110** from anywhere. Only `:2109` (STT) is in use.

## Design

### Port allocation on 4090 (within the open 2100–2110 range)

| Port | Service |
|------|---------|
| 2109 | STT (existing) |
| 2108 | Backend API + WebSocket (`/ws`, `/api/*`) — ESP32 + browser connect here |
| 2107 | Web frontend |

### A. Firmware — shared, zero per-device config

1. **Device identity from MAC.** On boot, derive `device_id = "esp32-" + last 6 hex of WiFi.macAddress()` (e.g. `esp32-CF3924`). Stable per chip, unique, no stored config. Same binary for every device.
2. **Send `hello` on WS connect.** First WS message: `{"type":"hello","device_id":"esp32-CF3924","name":"ESP32 CF3924"}`. Server already parses this.
3. **Connect to a public server host, not mDNS.** Replace the mDNS lookup with a compile-time constant `SERVER_HOST = "49.213.89.44"`, `SERVER_PORT = 2108`, path `/ws`. Keep WiFiManager for one-time WiFi entry. Remove the "halt on mDNS fail" branch; on disconnect, retry with backoff (no dead-end halt).
4. Keep the existing I2S capture + PCM streaming unchanged.

Result: flash → WiFiManager (enter WiFi once) → auto-connects to server → appears in device list.

### B. Backend — live device registry

- **On `hello`:** write a Redis hash `device:{device_id}` = `{device_id, name, connected_at, last_seen, ip}` and `SADD online_devices {device_id}`. Set/refresh a short TTL (e.g. 30s) heartbeat key `device_seen:{device_id}`.
- **Heartbeat:** refresh `last_seen` + TTL each time an audio frame (or periodic ping) arrives, so a hung device ages out.
- **On disconnect:** `SREM online_devices {device_id}` and mark offline.
- **New endpoint `GET /api/devices`** → list of online devices: `[{device_id, name, connected_at, last_seen}]`. Read from `online_devices` set, filtering by live TTL.

This extends the existing `connected_devices` usage rather than replacing it; rename to `online_devices` for clarity and add the metadata hash + TTL.

### C. Web — Devices / Scan page

- New page (sidebar entry "Devices"). On open and every ~3s (and on a manual **Scan** button) calls `GET /api/devices`.
- Renders a list/grid: device code, friendly name, online dot, "last seen Ns ago".
- Empty state: "No devices online — flash a mic and it'll appear here."
- No claiming/room assignment yet — just visibility.

### D. Deploy to 4090

- Reuse `docker-compose.yml`, minus the local `whisper` service (STT is the existing native `:2109` on the same host). Backend env `WHISPER_SERVICE_URL=http://localhost:2109` (host network) or `http://host.docker.internal:2109`.
- Publish backend on `2108:8000`, web on `2107:5173` (or a built static bundle behind the backend).
- Backend `DATABASE_URL`/`REDIS_URL` point at the compose db/redis services.
- ESP32 and browsers use `http://49.213.89.44:2107` (web) and `ws://49.213.89.44:2108/ws` (devices).
- Plain HTTP/WS for MVP; TLS/domain is a later step.

## Data flow

```
ESP32 (any) ──ws://49.213.89.44:2108/ws──┐
   hello{device_id from MAC}             │
   PCM frames ─────────────────────────► Backend (4090, :2108) ──► STT localhost:2109
                                          │  registry: online_devices + device:{id} (Redis, TTL)
Browser ──GET /api/devices (every 3s)────┘
   Devices page lists online mics
```

## Risks / notes

- **WiFi is still per-site.** "Upload and connect" still needs WiFi creds once via the WiFiManager portal (open AP `ESP32-Audio-Setup`). Server host is hardcoded, so no other config.
- **No TLS.** Fine for MVP; revisit if exposing publicly long-term.
- **Shared 4090.** App containers must not disturb training jobs; keep resource use modest (these services are light).
- **Reconnect.** Firmware must retry on disconnect instead of halting, so a device survives server restarts.
