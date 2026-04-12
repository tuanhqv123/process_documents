# Knowledge Base — Document RAG + Live Session Recorder

A local-first knowledge base that lets you upload documents (PDF, PPTX), extract structured layout via OCR, build a hierarchical knowledge graph, and run real-time RAG (Retrieval-Augmented Generation) against live voice sessions from an ESP32 microphone.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Browser (React + Vite)                    │
│  Dataset │ Workspaces │ Real-time Monitor │ Sessions │ Settings  │
└──────────────────────┬──────────────────────────────────────────┘
                       │ HTTP / WebSocket / SSE
┌──────────────────────▼──────────────────────────────────────────┐
│                   API Server  :8000  (FastAPI)                   │
│                                                                  │
│  /api/documents  ── upload, extract, train, OCR viewer          │
│  /api/workspaces ── group docs, semantic search                 │
│  /api/sessions   ── recording sessions, RAG blocks, summaries   │
│  /api/realtime   ── SSE audio levels + transcripts              │
│  /api/api-keys   ── manage OCR / LLM keys                       │
│  /ws             ── WebSocket for ESP32 raw PCM audio           │
│  /ws/audio-monitor── WebSocket broadcast to browser waveform    │
└──────┬───────────┬────────────────┬──────────────────┬──────────┘
       │           │                │                  │
┌──────▼──┐  ┌─────▼──────┐  ┌─────▼─────────┐  ┌────▼────────────┐
│Embedder │  │  Whisper   │  │  PostgreSQL   │  │  OCR / LLM      │
│ :8001   │  │   :8002    │  │  + pgvector   │  │  (vLLM/remote)  │
│MLX BGE  │  │MLX or      │  │  + ltree      │  │  dots.ocr model │
│small    │  │Transformers│  │               │  │                 │
└─────────┘  └────────────┘  └───────────────┘  └─────────────────┘
                                      ▲
                              ┌───────┴───────┐
                              │  ESP32 Device │
                              │  INMP441 mic  │
                              │  WiFi → WS   │
                              └───────────────┘
```

---

## Pipelines

### 1. Document ingestion pipeline

```
Upload PDF / PPTX
  │
  ├─ PDF  → pypdfium2 renders each page to PNG at 2x resolution
  └─ PPTX → python-pptx converts each slide to PNG
  │
  ▼
OCR (Extract)
  │  Each page PNG → HTTP POST → dots.ocr model (vLLM, OpenAI-compatible)
  │  Response: layout JSON with blocks per page
  │
  │  Block categories returned:
  │    Title, Section-header, Text, Table (HTML), Picture, Formula, Caption
  │
  └─ Page PNGs + OCR JSON saved to disk
  │
  ▼
Train (Knowledge Graph)
  │
  │  Build hierarchical DocumentNode tree in PostgreSQL (ltree paths):
  │
  │    Document (rank 0)
  │      └─ Title (rank 1)
  │           └─ Section-header (rank 2)
  │                └─ Text / Table / Picture / Formula  (rank 3, leaf)
  │
  │  Each leaf node stores:
  │    - text content (or caption for images)
  │    - category, page_num, bbox [x1,y1,x2,y2]
  │    - ltree path (e.g. doc_5.node_2.node_8.node_14)
  │
  ▼
Embed
  │  For each leaf node:
  │    context = ancestor Title + Section-header texts joined
  │    input   = "[context] text"
  │    → POST /embed → Embedder service (MLX BGE small-en-v1.5)
  │    → 384-dim float32 vector stored in document_nodes.embedding (pgvector)
  │
  └─ Document status → "ready"
```

---

### 2. Live session RAG pipeline

```
ESP32 (INMP441 mic)
  │  I2S 32-bit samples → 16-bit PCM with ~8x gain
  │  512 samples (32ms) per WebSocket binary frame
  │  Connects to ws://process-docs.local:8000/ws  (mDNS resolved)
  │
  ▼
API Server /ws endpoint
  │
  ├─ 1. Amplitude measurement (every incoming frame)
  │       compute RMS + peak from raw PCM
  │       accumulate for 1 second → average
  │       → SSE event "audio" to browser (wave chart on Real-time Monitor)
  │
  ├─ 2. Noise suppression (every incoming frame)
  │       WebRTC AudioProcessor — single-pass, level 3 aggressiveness
  │       10ms frame size = 320 bytes at 16kHz
  │       Voice activity detection: is_speech flag
  │       Hold logic: 15 frames of audio kept after speech ends (avoids cutoff)
  │       Non-speech frames → replaced with silence
  │       Clean PCM → broadcast to /ws/audio-monitor (browser waveform preview)
  │
  └─ 3. Whisper transcription (every ~2 seconds of buffered audio)
           64,000 bytes = 2 seconds of 16kHz 16-bit PCM
           → run_in_executor (thread) → POST /transcribe → Whisper service
           Whisper receives raw audio (handles its own noise model internally)
           Returns: transcript text string
           │
           ▼
        fire_session_rag_hook(device_id, text)
           │
           ├─ Look up active recording session (status = 'active')
           ├─ INSERT SessionTranscript row (block_id = NULL initially)
           │
           └─ check_and_flush: count unblocked transcripts for this session
                if count >= 5:
                  _flush_batch()
                    │
                    ├─ Collect all pending transcripts (ordered by time)
                    ├─ combined_text = join all transcript texts
                    │
                    ├─ Embed: POST /embed → 384-dim vector for combined_text
                    │
                    ├─ pgvector search in workspace document_nodes:
                    │     SELECT leaf nodes WHERE cosine similarity >= 0.65
                    │     JOIN workspace_docs to scope to the session's workspace
                    │     ORDER BY distance, LIMIT 3
                    │     For each result: walk ltree upward to get Title > Section breadcrumb
                    │
                    ├─ INSERT SessionRagBlock:
                    │     block_start / block_end timestamps
                    │     combined_text
                    │     rag_results (JSON: id, doc_id, filename, text, category,
                    │                        page_num, bbox, score, context breadcrumb)
                    │
                    └─ UPDATE transcripts.block_id = new block id

  Browser polls every 2s:
    GET /api/sessions/{id}/transcripts?after=<timestamp>  → live transcript feed
    GET /api/sessions/{id}/blocks?after=<timestamp>       → new RAG blocks

  On Stop:
    Flush any remaining unblocked transcripts
    Session status → "stopped"
    Background thread: generate_session_summary()
      → build prompt from all RAG blocks + matched document sections
      → POST to configured LLM (OpenAI-compatible, any model)
      → store summary in recording_sessions.summary
```

---

### 3. Database schema (key tables)

```
documents              — uploaded files (filename, status, page_count)
document_nodes         — OCR layout tree (ltree path, category, text, bbox, embedding vector)
workspaces             — named groups of documents
workspace_docs         — many-to-many: workspace ↔ document
recording_sessions     — name, status (idle/active/stopped), workspace_id, summary
session_transcripts    — individual Whisper outputs (session_id, text, created_at, block_id)
session_rag_blocks     — 5-transcript batches with RAG results JSON
api_keys               — OCR / LLM endpoint config (base_url, model_name, api_key)
```

**Extensions required:**
- `pgvector` — cosine similarity search on 384-dim embeddings
- `ltree` — hierarchical path queries for document node tree traversal

---

### 4. mDNS — how the ESP32 finds the server

```
API starts
  └─ subprocess: dns-sd -P process-docs _http._tcp local 8000 process-docs.local <LAN-IP>
       Bonjour registers the service name on the local network

ESP32 boots
  └─ MDNS.queryHost("process-docs", 2000ms timeout, up to 20 retries)
       Resolves hostname → LAN IP
  └─ webSocket.begin(resolvedIP, 8000, "/ws")
       Connects with the IP directly (no DNS dependency at runtime)
```

The server's LAN IP is detected automatically at startup via a UDP socket probe to `8.8.8.8` (no packet is sent — just reads the local interface). If mDNS fails on your router, hardcode the IP in the ESP32 firmware instead.

---

## Prerequisites

- **macOS with Apple Silicon** (M1/M2/M3) — MLX required for embedder and Whisper
- Python 3.10 – 3.13
- Node.js 18+ and npm
- PostgreSQL 14+ with **pgvector** and **ltree** extensions
- A running **OCR model** endpoint (OpenAI-compatible vLLM serving `rednote-hilab/dots.ocr`)

---

## Installation

### 1. Clone the repo

```bash
git clone <repo-url>
cd process_documents
```

### 2. Python virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e .
pip install mlx-whisper soundfile librosa webrtc-noise-gain python-pptx
```

### 3. Frontend

```bash
cd web
npm install
cd ..
```

### 4. Embedder

```bash
python3 -m venv embedder_venv
source embedder_venv/bin/activate
pip install mlx>=0.20 mlx-embeddings>=0.1.0 fastapi "uvicorn[standard]" pydantic>=2.0
```

---

## Database Setup

### Install PostgreSQL + pgvector (macOS)

```bash
brew install postgresql@16 pgvector
brew services start postgresql@16
```

### Create the database

```bash
psql postgres -c "CREATE DATABASE pdf_processor;"
psql postgres -c "CREATE USER postgres WITH PASSWORD 'postgres';"
psql postgres -c "GRANT ALL PRIVILEGES ON DATABASE pdf_processor TO postgres;"
```

### Schema

Tables, indexes, and extensions are created **automatically** on first API startup — no manual migrations needed. The API runs on boot:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS ltree;
-- then SQLAlchemy create_all()
```

---

## Configuration

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Database
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/pdf_processor

# Embedding service (MLX BGE — port 8001)
EMBEDDING_SERVICE_URL=http://localhost:8001
EMBEDDING_DIM=384

# Redis (optional)
REDIS_URL=redis://localhost:6379

# OCR model — OpenAI-compatible endpoint serving dots.ocr
DOTS_OCR_URL=http://<your-vllm-host>:<port>/v1
DOTS_OCR_MODEL=rednote-hilab/dots.ocr

# Whisper model
WHISPER_MODEL=mlx-community/whisper-large-v3-turbo

# OCR processing tuning
OCR_PARALLEL_WORKERS=5
OCR_MAX_RETRIES=2
```

> OCR, LLM, and embedding keys can also be configured at runtime via **Settings** in the UI (stored in the database and take priority over `.env`).

---

## Starting the Services

Open **4 separate terminals** from the project root:

### Terminal 1 — API server (port 8000)

```bash
source venv/bin/activate
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

### Terminal 2 — Whisper (port 8002)

Two backends available — pick one:

**Option A — MLX (Apple Silicon, recommended on macOS)**

```bash
source venv/bin/activate
pip install mlx-whisper   # first time only

WHISPER_MODEL=mlx-community/whisper-large-v3-turbo \
uvicorn whisper.main_mlx:app --host 0.0.0.0 --port 8002 --reload
```

First run downloads the model (~800 MB, cached after that).

**Option B — HuggingFace Transformers (Linux / cross-platform)**

```bash
source venv/bin/activate
pip install torch transformers accelerate   # first time only

WHISPER_MODEL=openai/whisper-medium.en \
uvicorn whisper.main:app --host 0.0.0.0 --port 8002 --reload
```

Both options expose the same HTTP API on port 8002, so the rest of the stack works unchanged.

### Terminal 3 — Embedder MLX (port 8001)

```bash
# First time only — create a separate venv for the embedder
python3 -m venv embedder_venv
source embedder_venv/bin/activate
pip install mlx>=0.20 mlx-embeddings>=0.1.0 fastapi uvicorn[standard] pydantic>=2.0

# Every time
source embedder_venv/bin/activate
uvicorn embedder.main:app --host 0.0.0.0 --port 8001
```

> The embedder currently requires MLX (Apple Silicon). A cross-platform `sentence-transformers` version is not yet included.

### Terminal 4 — Frontend (port 5173)

```bash
cd web
npm run dev
```

Open **http://localhost:5173**

### Verify all services are up

```bash
curl http://localhost:8000/api/health
curl http://localhost:8001/health
curl http://localhost:8002/health
```

---

## mDNS — Auto-discovery on Local Network

The API server automatically registers itself as **`process-docs.local`** on your local network using macOS Bonjour (`dns-sd`) when it starts. This means the ESP32 can connect by hostname instead of a hardcoded IP address.

```
API starts → dns-sd registers process-docs.local → port 8000
ESP32 connects to ws://process-docs.local:8000/ws
```

### How it works

On startup, `api/main.py` runs:

```bash
dns-sd -P process-docs _http._tcp local 8000 process-docs.local <your-lan-ip>
```

This broadcasts the service over mDNS so any device on the same WiFi network can resolve `process-docs.local`.

### Verify it works

From another device on the same network (or the Mac itself):

```bash
ping process-docs.local
# or
curl http://process-docs.local:8000/api/health
```

### Requirements

- macOS only (`dns-sd` is built into macOS via Bonjour — no extra install needed)
- Both the Mac and ESP32 must be on the **same WiFi network**
- If your router blocks mDNS between devices, use the Mac's IP address directly instead

### ESP32 firmware — use mDNS hostname

In your ESP32 firmware `config.h`, you can use the hostname instead of IP:

```cpp
#define WS_HOST  "process-docs.local"   // works via mDNS
#define WS_PORT  8000
#define WS_PATH  "/ws"
```

> If mDNS doesn't resolve on your network, fall back to the Mac's LAN IP:
> ```bash
> ipconfig getifaddr en0
> ```

---

## ESP32 Firmware

The ESP32 streams **16 kHz mono PCM** audio over WebSocket to `ws://<mac-ip>:8000/ws`.

Firmware repo: **https://github.com/tuanhqv123/NLP**

### Setup steps

1. Clone the ESP32 firmware repo
2. Open in Arduino IDE or PlatformIO
3. Edit `config.h` with your WiFi and server details:

```cpp
#define WIFI_SSID     "your-wifi-name"
#define WIFI_PASSWORD "your-wifi-password"
#define WS_HOST       "192.168.x.x"   // your Mac's LAN IP
#define WS_PORT       8000
#define WS_PATH       "/ws"
```

4. Flash to the ESP32
5. On boot the device auto-connects — the **Real-time Monitor** page shows the live wave chart

Find your Mac's LAN IP:

```bash
ipconfig getifaddr en0
```

---

## Usage Guide

### 1. Configure OCR model

Go to **Settings → Add Key → Type: OCR**, enter your vLLM base URL and model name (`rednote-hilab/dots.ocr`). Click **Test** to verify.

### 2. Upload and process a document

1. **Dataset → Upload** — PDF or PPTX
2. Extraction starts automatically (OCR runs page-by-page, progress shown)
3. After extraction completes → click **Train** to build the knowledge graph and embed all nodes
4. Status becomes **ready**

### 3. Create a workspace and add documents

1. Click **+ New Workspace** in the sidebar
2. Open the workspace → **Add from Dataset** to add trained documents
3. Use the search bar to test semantic search

### 4. Run a live recording session

1. Go to **Sessions → New Session**, pick a name and select a workspace
2. Open the session → click **Start Recording**
3. Speak near the ESP32 microphone
4. Transcripts appear live; every 5 sentences the system searches the workspace and shows relevant document sections on the right panel
5. Click **Stop** — a summary is generated automatically via LLM

---

## Project Structure

```
process_documents/
├── api/
│   ├── main.py                  # FastAPI app, WebSocket (ESP32), WebRTC NS
│   ├── db.py                    # SQLAlchemy models + DB init
│   ├── config.py                # Settings (env vars)
│   ├── whisper_client.py        # HTTP client → Whisper service
│   ├── embedding_client.py      # HTTP client → Embedder service
│   ├── routes/
│   │   ├── documents.py         # Upload, list, delete
│   │   ├── extract.py           # OCR extract, train, graph, page images
│   │   ├── workspaces.py        # Workspace CRUD + vector search
│   │   ├── sessions.py          # Session CRUD, transcripts, RAG blocks
│   │   ├── realtime.py          # SSE audio levels + transcripts
│   │   └── api_keys.py          # OCR / LLM key management
│   └── services/
│       ├── ocr_llm.py           # PDF/PPTX → PNG → dots.ocr → layout JSON
│       ├── knowledge_graph.py   # Build node tree + embed leaf nodes
│       └── session_service.py   # Transcript save, RAG batch flush, LLM summary
├── embedder/
│   └── main.py                  # MLX BGE embedding service (:8001)
├── whisper/
│   ├── main_mlx.py              # MLX Whisper service (:8002)
│   └── main.py                  # Transformers Whisper (legacy fallback)
├── web/                         # React + Vite + Tailwind + shadcn/ui
│   └── src/
│       ├── pages/               # DatasetPage, WorkspacePage, SessionDetailPage…
│       └── components/          # OcrViewer, UploadModal, AppSidebar…
├── .env.example
├── pyproject.toml
└── embedder_venv/                # separate venv for the embedder (created on first setup)
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, shadcn/ui |
| Backend | FastAPI, SQLAlchemy 2, PostgreSQL + pgvector + ltree |
| OCR | rednote-hilab/dots.ocr via vLLM (OpenAI-compatible API) |
| Embedding | MLX BGE small-en-v1.5-4bit (`embedder/main.py`, Apple Silicon) |
| Speech-to-Text | MLX Whisper (`whisper/main_mlx.py`) or HuggingFace Transformers (`whisper/main.py`) |
| Noise Suppression | webrtc-noise-gain level 3 (server-side) |
| Document Rendering | pypdfium2 (PDF), python-pptx (PPTX) |
| Knowledge Graph | PostgreSQL ltree — hierarchical node paths |
