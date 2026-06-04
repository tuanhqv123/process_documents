# RUNBOOK — Deploy + Connect ESP32 Mics (AI-executable, end-to-end)

This is a self-contained runbook. An AI agent (or human) with shell + SSH access can follow it top-to-bottom to (1) deploy the whole stack to the GPU server, (2) flash an ESP32, and (3) verify a mic is connected and contributing to a session. Every step has an exact command and an expected result. Do steps in order; do not skip verification.

---

## 0. System facts (read first)

| Thing | Value |
|-------|-------|
| App repo (local) | `/Users/tuantran/WorkSpace/process_documents`, branch `feature/esp32-discovery-deploy` |
| GPU server | SSH alias **`Model_Training_Server`** = `49.213.89.44`, user `masan2025`, port `234` (key in `~/WorkSpace/keys/`). Hostname `s4090-1x-01-train`, Ubuntu 24.04, RTX 4090. **Shared box — don't disturb other GPU jobs.** |
| Server app dir | `~/process_documents` (synced from local) |
| **Single public port** | **`2108`** — nginx reverse proxy; the ONLY public app port. Cloud security group opens TCP `2100–2110`. |
| Internal routing (nginx) | `/api` + `/ws*` → `backend:8000`; `/` → `frontend:5173` |
| STT (speech-to-text) | Native on server `:2109` (Zipformer, sherpa-onnx CUDA), dir `~/zipformer-asr`. Backend calls it at `host.docker.internal:2109`. |
| Web URL | `http://49.213.89.44:2108` |
| ESP32 endpoint | `ws://49.213.89.44:2108/ws` (hardcoded in firmware) |
| Default login | `admin` / `admin123` (register if DB is fresh) |
| Firmware | `firmware/` (PlatformIO). Shared binary; each ESP32 derives `device_id` from MAC. |

Architecture:
```
ESP32 (any, MAC-based id) ──ws://49.213.89.44:2108/ws──┐
                                                       ├─ nginx:2108 ─┬─ /api,/ws → backend:8000 ─→ STT host:2109
Browser ── http://49.213.89.44:2108/ ──────────────────┘              └─ /        → frontend:5173
backend ↔ db (postgres/pgvector) + redis (device registry, TTL)
```

---

## 1. Deploy / update the server stack

### 1.1 Confirm STT is up on the server (prerequisite)
```bash
ssh Model_Training_Server 'curl -s --max-time 5 http://localhost:2109/health'
```
Expect JSON containing `"provider":"cuda"`. If empty: start it first — `ssh Model_Training_Server 'docker start zipformer-asr'` (image `zipformer-asr:gpu`, see `~/zipformer-asr`), then re-check.

### 1.2 Sync the repo to the server
From the local repo root:
```bash
rsync -az --delete \
  --exclude '.git' --exclude 'web/node_modules' --exclude 'data' \
  --exclude 'models' --exclude 'embedder_venv' --exclude '__pycache__' --exclude 'firmware/.pio' \
  -e ssh /Users/tuantran/WorkSpace/process_documents/ \
  Model_Training_Server:~/process_documents/
```
Expect: completes with no error.

### 1.3 Ensure server `.env` exists
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

### 1.4 Build + start (db, redis, backend, frontend, nginx — NOT whisper; STT is native)
```bash
ssh Model_Training_Server 'cd ~/process_documents && docker compose up -d --build db redis backend frontend nginx'
```
Expect all five `pdf-*` containers `Started`. First build takes a few minutes.

> Notes: db/redis have **no published host ports** (the server already runs native postgres:5432 + redis:6379). `mlx`/`mlx-embeddings` are intentionally NOT in backend deps (Mac-only, unused by `api/`). If the build fails on a missing module, add it to `pyproject.toml` (the Dockerfile runs `pip install .`).

### 1.5 Verify the public port (from any machine)
```bash
curl -s --max-time 8 http://49.213.89.44:2108/api/health     # -> {"status":"ok"}
curl -s --max-time 8 http://49.213.89.44:2108/api/devices    # -> [] or a JSON array of devices
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://49.213.89.44:2108/   # -> HTTP 200
```

### 1.6 Ensure a login exists (fresh DB has none)
```bash
curl -s -X POST http://49.213.89.44:2108/api/auth/register \
  -H "Content-Type: application/json" -d '{"username":"admin","password":"admin123"}' \
  -o /dev/null -w "register HTTP %{http_code}\n"   # 200 = created, 400 = already exists
```

---

## 2. Flash an ESP32 (any board, identical hardware)

Full human guide: [`firmware/README.md`](../firmware/README.md). Minimal AI path:

### 2.1 Build + upload (port auto-detected)
```bash
cd /Users/tuantran/WorkSpace/process_documents/firmware
pio run -t upload
```
Expect `[SUCCESS]` and `Hard resetting via RTS pin...`. (Do NOT pass a port; platformio.ini auto-detects. A data USB cable must be used.)

### 2.2 First-time WiFi (one-time, manual)
The ESP32 has no saved WiFi until set: it broadcasts an open AP **`ESP32-Audio-Setup`**. On a phone, join it → captive portal (or `192.168.4.1`) → pick a WiFi **with internet** → Save. It reboots and connects. (To re-do later: hold `BOOT` ~3s at power-on to erase saved WiFi.)

### 2.3 Confirm from serial (optional, resets the board on open)
```bash
cd /Users/tuantran/WorkSpace/process_documents/firmware && pio device monitor
```
Expect: `Device ID: esp32-XXXXXX`, `Server: 49.213.89.44:2108/ws`, `WebSocket connected`, `Sent hello: {...}`, then `[STATS] ... | Connected`.

---

## 3. Verify a mic end-to-end (server side, non-invasive)

```bash
# The device should appear in the live registry (replace XXXXXX with the board's MAC suffix, or just inspect the array):
curl -s http://49.213.89.44:2108/api/devices
```
Expect an entry like:
```json
[{"device_id":"esp32-CF3924","name":"ESP32 CF3924","connected_at":"...","last_seen":"...","ip":"172.x.x.x"}]
```
`device_id` = `esp32-` + last 6 hex of the chip MAC (unique per board). `ip` is the nginx container IP (traffic came through the single public port — correct). `last_seen` updates every few seconds (heartbeat).

Cross-check Redis directly if needed:
```bash
ssh Model_Training_Server 'docker exec pdf-redis redis-cli SMEMBERS online_devices'
```

TTL behavior: power off the board → after ~30s it drops out of `/api/devices` (TTL expiry + disconnect prune).

Web check: open `http://49.213.89.44:2108`, log in (`admin`/`admin123`), sidebar **Devices** → the mic shows online and updates every ~3s.

---

## 4. Operate: share a session so multiple mics contribute

Current model: **one globally-active session at a time**; every online mic feeds whichever session is `Start`ed (transcripts tagged by `device_id`).

1. Web → create a session → **Start** (it becomes the active session).
2. Open the session → **Share** → copy the 8-char invite code → send it to the other person.
3. Other person: log in → **Sessions → Join** → enter the code → they see the shared session.
4. Both mics (each just needs to be online per §2) now stream into that session. No ESP32-side action needed.

> Multiple independent rooms running at once (assigning specific mics to specific rooms) is a **deferred feature** — not built yet.

---

## 5. Container / log operations

```bash
ssh Model_Training_Server 'cd ~/process_documents && docker compose ps'
ssh Model_Training_Server 'docker logs -f pdf-backend'          # backend logs (hello/ws/transcripts)
ssh Model_Training_Server 'docker logs -f pdf-nginx'            # proxy logs
ssh Model_Training_Server 'cd ~/process_documents && docker compose restart backend'
ssh Model_Training_Server 'cd ~/process_documents && docker compose up -d --build backend'  # after code change
```
After editing backend code locally: re-run §1.2 (rsync) then rebuild backend. The backend container mounts `./api` with `--reload`, but a persistent ESP32 WebSocket can block uvicorn graceful reload — prefer `docker compose restart backend` if a reload hangs.

---

## 6. Troubleshooting

| Symptom | Check / fix |
|---------|-------------|
| `/api/health` times out from outside | Is nginx up? `docker compose ps`. Is port 2108 published? `docker port pdf-nginx`. Cloud SG must allow 2108 (in 2100–2110). |
| Web loads but API calls fail | nginx routes `/api` → backend; check `docker logs pdf-backend` for startup errors / missing modules. |
| Backend won't start: `ModuleNotFoundError` | Add the package to `pyproject.toml` deps, rsync, `docker compose up -d --build backend`. |
| Register/login returns 500 (bcrypt) | `pyproject.toml` must pin `bcrypt<4.1` (passlib 1.7.4 incompatibility). |
| `pdf-redis`/`pdf-db` fail to bind a port | They must have NO `ports:` mapping (server runs native pg/redis). Internal-only via compose network. |
| ESP32 not in `/api/devices` | Serial shows `WebSocket connected`? If yes but absent on server, the board can't reach `49.213.89.44:2108` (WiFi has no internet / firewall). `curl http://49.213.89.44:2108/api/health` from the board's network. |
| ESP32 serial = garbage | Wrong baud; use `pio device monitor` (115200). Repeating garbage with no boot banner = old/halted firmware → re-flash (§2.1). |
| STT returns nothing | `ssh Model_Training_Server 'curl -s localhost:2109/health'` → must be `"provider":"cuda"`. Restart `zipformer-asr` if down. |

---

## 7. What each piece is (for an agent modifying it)

- `api/redis_client.py` — device registry: `register_device` / `touch_device` / `unregister_device` / `get_online_devices` (Redis set `online_devices` + hash `device:{id}`, 30s TTL).
- `api/main.py` `@app.websocket("/ws")` — parses `hello{device_id,name}`, registers device, streams PCM → denoise → STT → transcript, heartbeats, unregisters on disconnect.
- `api/routes/devices.py` — `GET /api/devices`.
- `web/src/pages/devices-page.tsx` — polls `/api/devices` every 3s (sidebar "Devices").
- `deploy/nginx.conf` — single-port reverse proxy.
- `docker-compose.yml` — db, redis, backend (internal), frontend (internal), nginx (public 2108), whisper (local-only, NOT used on server).
- `firmware/src/main.cpp` — `SERVER_HOST`/`SERVER_PORT` at top; MAC→`device_id`; `hello` on connect; auto-reconnect.
- Specs/plans: `docs/superpowers/specs/2026-06-04-esp32-discovery-and-server-deploy-design.md`, `docs/superpowers/plans/2026-06-04-esp32-discovery-and-server-deploy.md`.
