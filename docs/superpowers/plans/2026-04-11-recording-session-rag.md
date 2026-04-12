# Recording Session + RAG Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a recording session feature where users select a workspace, record live speech, see real-time batched RAG results alongside timestamped transcript blocks, and receive an LLM-generated summary when the session ends.

**Architecture:**
Two-level storage: `session_transcripts` stores every individual transcript line with its timestamp (for display); `session_rag_blocks` stores 10-second windows — each block holds the combined text of all transcripts in that window, plus the RAG results as JSON. A background thread fires every 10 s per active session, grabs all unblocked transcripts, concatenates them, runs one vector search, creates a block row, and links the transcripts to it via `block_id`. The frontend polls `/api/sessions/{id}/blocks?after=<ts>` every 5 s and renders blocks as cards: each card shows the time range + individual timestamped lines on the left, and the page image + section breadcrumb on the right for the selected block. Stopping a session sends all blocks to the LLM and saves a summary.

**Why batching over per-sentence RAG:**
A single 2-second Whisper chunk is often a fragment ("the"). Combining 10 s of speech into one query gives the embedding model enough context to find the right section. Individual timestamps are still preserved inside each block so the user can see exactly when each sentence was spoken.

**Tech Stack:** FastAPI · PostgreSQL (pgvector, ltree) · Redis · React 18 · TypeScript · Vite · Tailwind · shadcn/ui · react-router-dom

---

## File Map

| Action  | Path                                               | Responsibility                                            |
|---------|----------------------------------------------------|-----------------------------------------------------------|
| Modify  | `api/db.py`                                        | Add `RecordingSession`, `SessionTranscript`, `SessionRagBlock` |
| Create  | `api/services/session_service.py`                  | Transcript save, 10-s batch aggregator, LLM summary       |
| Create  | `api/routes/sessions.py`                           | REST: CRUD, start/stop, blocks poll, summarize            |
| Modify  | `api/main.py`                                      | Include sessions router; hook binary-WS transcript        |
| Modify  | `api/routes/realtime.py`                           | Hook HTTP + WS-text transcript saves                      |
| Modify  | `web/src/types/index.ts`                           | Add Session, SessionTranscript, SessionRagBlock types     |
| Modify  | `web/src/api/client.ts`                            | Add `api.sessions.*` methods                              |
| Create  | `web/src/pages/sessions-page.tsx`                  | List all sessions, create new, delete                     |
| Create  | `web/src/pages/session-detail-page.tsx`            | Split view: block list left, RAG context right            |
| Modify  | `web/src/components/app-sidebar.tsx`               | Add "Sessions" nav item                                   |
| Modify  | `web/src/App.tsx`                                  | Add `/sessions` and `/sessions/:id` routes + state        |

---

## Task 1: Database Models

**Files:**
- Modify: `api/db.py`

- [ ] **Step 1: Add three new ORM models to `api/db.py`**

  After `class WorkspaceDoc` (around line 170) and before `def get_db()`, add:

  ```python
  class RecordingSession(Base):
      __tablename__ = "recording_sessions"

      id = Column(Integer, primary_key=True, autoincrement=True)
      name = Column(String, nullable=False)
      workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True)
      status = Column(String, default="idle")   # idle | active | stopped
      created_at = Column(DateTime, default=datetime.utcnow)
      started_at = Column(DateTime, nullable=True)
      ended_at = Column(DateTime, nullable=True)
      summary = Column(Text, nullable=True)     # LLM-generated summary at session end


  class SessionTranscript(Base):
      """One row per Whisper chunk (~2 s). Linked to a RAG block once aggregated."""
      __tablename__ = "session_transcripts"

      id = Column(Integer, primary_key=True, autoincrement=True)
      session_id = Column(Integer, ForeignKey("recording_sessions.id", ondelete="CASCADE"),
                          nullable=False, index=True)
      block_id = Column(Integer, ForeignKey("session_rag_blocks.id", ondelete="SET NULL"),
                        nullable=True, index=True)   # NULL until the 10-s batch fires
      device_id = Column(String, default="esp32-001")
      text = Column(Text, nullable=False)
      timestamp = Column(DateTime, default=datetime.utcnow)


  class SessionRagBlock(Base):
      """10-second aggregation window: combined text + RAG results for that window."""
      __tablename__ = "session_rag_blocks"

      id = Column(Integer, primary_key=True, autoincrement=True)
      session_id = Column(Integer, ForeignKey("recording_sessions.id", ondelete="CASCADE"),
                          nullable=False, index=True)
      block_start = Column(DateTime, nullable=False)  # timestamp of earliest transcript in window
      block_end = Column(DateTime, nullable=False)    # timestamp of latest transcript in window
      combined_text = Column(Text, nullable=False)    # all transcript texts joined by space
      rag_results = Column(Text, default="[]")        # JSON list of SearchResult-shaped dicts
  ```

  > **Note:** `SessionTranscript.block_id` references `session_rag_blocks.id`, which is defined after it in the file. PostgreSQL resolves FK constraints by name at `CREATE TABLE` time, so the order in the file is fine. SQLAlchemy `create_all` handles dependency ordering automatically.

- [ ] **Step 2: Run DB migration**

  ```bash
  cd /Users/tuantran/WorkSpace/process_documents
  python -c "from api.db import init_db; init_db(); print('Tables created')"
  ```
  Expected: `Tables created` (no errors)

- [ ] **Step 3: Commit**

  ```bash
  git add api/db.py
  git commit -m "feat: add RecordingSession, SessionTranscript, SessionRagBlock DB models"
  ```

---

## Task 2: Session Service

**Files:**
- Create: `api/services/session_service.py`

This file owns three responsibilities:
1. **Save individual transcript** — inserts a `SessionTranscript` row for the active session
2. **Batch aggregator** — combines unblocked transcripts into a `SessionRagBlock` every 10 s
3. **LLM summary** — at session end, builds a prompt from all blocks and calls the active LLM

- [ ] **Step 1: Create `api/services/session_service.py`**

  ```python
  """Session service: per-transcript save, 10-s RAG batch aggregator, LLM summary."""

  import json
  import logging
  import threading
  from datetime import datetime

  from sqlalchemy import text

  from api.db import (
      RecordingSession, SessionTranscript, SessionRagBlock, get_session
  )

  logger = logging.getLogger(__name__)

  # ── Active session lookup ─────────────────────────────────────────────────────

  def get_active_session_id() -> int | None:
      """Return the ID of the currently active (status='active') session, or None."""
      db = get_session()
      try:
          row = db.execute(
              text("SELECT id FROM recording_sessions WHERE status = 'active' LIMIT 1")
          ).first()
          return row[0] if row else None
      finally:
          db.close()


  # ── Save individual transcript ────────────────────────────────────────────────

  def save_session_transcript(session_id: int, device_id: str, text_: str) -> None:
      """Insert one SessionTranscript row (block_id=NULL — aggregator fills it later)."""
      db = get_session()
      try:
          t = SessionTranscript(
              session_id=session_id,
              device_id=device_id,
              text=text_,
              timestamp=datetime.utcnow(),
          )
          db.add(t)
          db.commit()
      except Exception as e:
          logger.error(f"save_session_transcript error: {e}")
          db.rollback()
      finally:
          db.close()


  # ── 10-second batch aggregator ────────────────────────────────────────────────

  # Timer handle: one per active session, reset on each fire
  _batch_timers: dict[int, threading.Timer] = {}
  _timer_lock = threading.Lock()
  BATCH_SECONDS = 10


  def schedule_batch(session_id: int) -> None:
      """Cancel any existing timer for this session and schedule a fresh one.

      Called every time a transcript arrives for the session.  After BATCH_SECONDS
      of silence the timer fires and flushes the pending transcripts into a RAG block.
      """
      with _timer_lock:
          existing = _batch_timers.get(session_id)
          if existing:
              existing.cancel()
          t = threading.Timer(BATCH_SECONDS, _flush_batch, args=[session_id])
          t.daemon = True
          t.start()
          _batch_timers[session_id] = t


  def cancel_batch(session_id: int) -> None:
      """Cancel the pending timer and immediately flush (called on session stop)."""
      with _timer_lock:
          existing = _batch_timers.pop(session_id, None)
          if existing:
              existing.cancel()
      # Flush whatever is left right now
      _flush_batch(session_id)


  def _flush_batch(session_id: int) -> None:
      """Collect unblocked transcripts, run RAG on combined text, create a SessionRagBlock."""
      db = get_session()
      try:
          session = db.query(RecordingSession).filter(
              RecordingSession.id == session_id
          ).first()
          if not session:
              return

          # Grab all unblocked transcripts for this session, oldest first
          pending = (
              db.query(SessionTranscript)
              .filter(
                  SessionTranscript.session_id == session_id,
                  SessionTranscript.block_id == None,  # noqa: E711
              )
              .order_by(SessionTranscript.timestamp)
              .all()
          )
          if not pending:
              return

          combined_text = " ".join(t.text for t in pending)
          block_start = pending[0].timestamp
          block_end = pending[-1].timestamp

          # Run RAG if workspace is set
          rag_results: list[dict] = []
          if session.workspace_id:
              rag_results = _search_workspace(session.workspace_id, combined_text, db)

          block = SessionRagBlock(
              session_id=session_id,
              block_start=block_start,
              block_end=block_end,
              combined_text=combined_text,
              rag_results=json.dumps(rag_results),
          )
          db.add(block)
          db.flush()  # get block.id

          for t in pending:
              t.block_id = block.id

          db.commit()
          logger.info(
              f"[session {session_id}] RAG block #{block.id}: "
              f"{len(pending)} transcripts, {len(rag_results)} matches"
          )
      except Exception as e:
          logger.error(f"_flush_batch error: {e}")
          db.rollback()
      finally:
          db.close()


  # ── Vector search ─────────────────────────────────────────────────────────────

  def _search_workspace(workspace_id: int, query: str, db) -> list[dict]:
      """Embed `query` and search workspace leaf nodes. Returns list of result dicts."""
      from api.embedding_client import embedding_client

      try:
          q_emb = embedding_client.embed_single(query)
      except Exception as e:
          logger.warning(f"Embedding unavailable: {e}")
          return []

      rows = db.execute(
          text("""
              SELECT
                  n.id, n.doc_id, d.filename,
                  n.text, n.category, n.page_num,
                  COALESCE(n.bbox, '{}') AS bbox,
                  n.path,
                  1 - (n.embedding <=> CAST(:qemb AS vector)) AS score
              FROM document_nodes n
              JOIN documents d ON d.id = n.doc_id
              JOIN workspace_docs wd ON wd.doc_id = n.doc_id
              WHERE wd.workspace_id = :ws_id
                AND n.node_rank = 3
                AND n.embedding IS NOT NULL
                AND n.text != ''
              ORDER BY n.embedding <=> CAST(:qemb AS vector)
              LIMIT 5
          """),
          {"qemb": str(q_emb), "ws_id": workspace_id},
      ).fetchall()

      results = []
      for r in rows:
          node_id, doc_id, filename, node_text, category, page_num, bbox, path, score = r
          ancestors = db.execute(
              text("""
                  SELECT category, text FROM document_nodes
                  WHERE CAST(path AS ltree) @> CAST(:node_path AS ltree)
                    AND path != :node_path
                    AND category IN ('Title', 'Section-header') AND text != ''
                  ORDER BY depth ASC
              """),
              {"node_path": path},
          ).fetchall()
          breadcrumb = " > ".join(a.text for a in ancestors if a.text)
          if node_text:
              breadcrumb = (breadcrumb + " > " + node_text) if breadcrumb else node_text
          results.append({
              "id": node_id, "doc_id": doc_id, "filename": filename,
              "text": node_text or "", "context": breadcrumb,
              "category": category, "page_num": page_num or 0,
              "bbox": list(bbox) if bbox else [], "score": float(score),
          })
      return results


  # ── LLM summary ───────────────────────────────────────────────────────────────

  def generate_session_summary(session_id: int) -> str:
      """Build a prompt from all RAG blocks, call the active LLM, return summary text."""
      db = get_session()
      try:
          session = db.query(RecordingSession).filter(
              RecordingSession.id == session_id
          ).first()
          if not session:
              return ""

          ws_row = db.execute(
              text("SELECT name FROM workspaces WHERE id = :id"),
              {"id": session.workspace_id},
          ).first() if session.workspace_id else None
          ws_name = ws_row[0] if ws_row else "Unknown"

          blocks = (
              db.query(SessionRagBlock)
              .filter(SessionRagBlock.session_id == session_id)
              .order_by(SessionRagBlock.block_start)
              .all()
          )
          if not blocks:
              return "No transcript data was recorded in this session."

          lines = [
              f'Recording session: "{session.name}"',
              f'Workspace: "{ws_name}"',
              "",
              "Transcript blocks with matched document sections:",
              "",
          ]
          for b in blocks:
              start = b.block_start.strftime("%H:%M:%S")
              end = b.block_end.strftime("%H:%M:%S")
              lines.append(f"[{start} – {end}] User said: \"{b.combined_text}\"")
              rag = json.loads(b.rag_results or "[]")
              if rag:
                  top = rag[0]
                  lines.append(
                      f"  → Relevant in \"{top['filename']}\", "
                      f"page {top['page_num']}: {top['context']}"
                  )
              lines.append("")

          prompt = "\n".join(lines) + (
              "\nWrite a concise session summary covering:\n"
              "1. What the user discussed and asked about\n"
              "2. Which document sections were most relevant\n"
              "3. Key insights from the session\n\n"
              "Use markdown with headers."
          )
          return _call_llm(prompt)
      finally:
          db.close()


  def _call_llm(prompt: str) -> str:
      from openai import OpenAI
      from api.db import ApiKey

      db = get_session()
      try:
          active = db.query(ApiKey).filter(
              ApiKey.type == "llm", ApiKey.is_active == True  # noqa: E712
          ).first()
          if not active:
              return "No active LLM configured. Go to Settings → add an LLM API key."
          client = OpenAI(api_key=active.api_key or "0", base_url=active.base_url.rstrip("/"))
          model = active.model_name or "default"
      finally:
          db.close()

      resp = client.chat.completions.create(
          model=model,
          messages=[
              {
                  "role": "system",
                  "content": (
                      "You are a knowledgeable assistant summarizing a voice recording session. "
                      "Be concise and structured. Use markdown."
                  ),
              },
              {"role": "user", "content": prompt},
          ],
          max_tokens=1024,
          temperature=0.3,
          extra_body={"chat_template_kwargs": {"enable_thinking": False}},
      )
      return (resp.choices[0].message.content or "").strip()
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add api/services/session_service.py
  git commit -m "feat: add session_service (save transcript, 10-s RAG batch, LLM summary)"
  ```

---

## Task 3: Sessions API Routes

**Files:**
- Create: `api/routes/sessions.py`

- [ ] **Step 1: Create `api/routes/sessions.py`**

  ```python
  """REST endpoints for recording sessions."""

  import json
  import threading
  from datetime import datetime
  from typing import Optional

  from fastapi import APIRouter, HTTPException, Depends
  from pydantic import BaseModel
  from sqlalchemy import text

  from api.db import get_db, RecordingSession, SessionTranscript, SessionRagBlock
  from api.services.session_service import generate_session_summary, cancel_batch

  router = APIRouter(prefix="/api/sessions", tags=["sessions"])


  # ── Pydantic schemas ──────────────────────────────────────────────────────────

  class SessionCreate(BaseModel):
      name: str
      workspace_id: Optional[int] = None


  class RagResultOut(BaseModel):
      id: int
      doc_id: int
      filename: str
      text: str
      context: str
      category: str
      page_num: int
      bbox: list[float]
      score: float


  class TranscriptLineOut(BaseModel):
      id: int
      device_id: str
      text: str
      timestamp: str  # ISO


  class RagBlockOut(BaseModel):
      id: int
      session_id: int
      block_start: str   # ISO
      block_end: str     # ISO
      combined_text: str
      rag_results: list[RagResultOut]
      transcripts: list[TranscriptLineOut]  # individual lines inside this block


  class SessionOut(BaseModel):
      id: int
      name: str
      workspace_id: Optional[int]
      workspace_name: Optional[str]
      status: str
      created_at: str
      started_at: Optional[str]
      ended_at: Optional[str]
      summary: Optional[str]
      block_count: int
      transcript_count: int


  # ── Helpers ───────────────────────────────────────────────────────────────────

  def _session_out(s: RecordingSession, db) -> SessionOut:
      ws_name = None
      if s.workspace_id:
          row = db.execute(
              text("SELECT name FROM workspaces WHERE id = :id"),
              {"id": s.workspace_id},
          ).first()
          ws_name = row[0] if row else None
      block_count = db.query(SessionRagBlock).filter(
          SessionRagBlock.session_id == s.id
      ).count()
      transcript_count = db.query(SessionTranscript).filter(
          SessionTranscript.session_id == s.id
      ).count()
      return SessionOut(
          id=s.id,
          name=s.name,
          workspace_id=s.workspace_id,
          workspace_name=ws_name,
          status=s.status,
          created_at=s.created_at.isoformat(),
          started_at=s.started_at.isoformat() if s.started_at else None,
          ended_at=s.ended_at.isoformat() if s.ended_at else None,
          summary=s.summary,
          block_count=block_count,
          transcript_count=transcript_count,
      )


  def _block_out(b: SessionRagBlock, db) -> RagBlockOut:
      transcripts = (
          db.query(SessionTranscript)
          .filter(SessionTranscript.block_id == b.id)
          .order_by(SessionTranscript.timestamp)
          .all()
      )
      rag = json.loads(b.rag_results or "[]")
      return RagBlockOut(
          id=b.id,
          session_id=b.session_id,
          block_start=b.block_start.isoformat(),
          block_end=b.block_end.isoformat(),
          combined_text=b.combined_text,
          rag_results=[RagResultOut(**r) for r in rag],
          transcripts=[
              TranscriptLineOut(
                  id=t.id,
                  device_id=t.device_id,
                  text=t.text,
                  timestamp=t.timestamp.isoformat(),
              )
              for t in transcripts
          ],
      )


  # ── Routes ────────────────────────────────────────────────────────────────────

  @router.get("", response_model=list[SessionOut])
  def list_sessions(db=Depends(get_db)):
      sessions = (
          db.query(RecordingSession)
          .order_by(RecordingSession.created_at.desc())
          .all()
      )
      return [_session_out(s, db) for s in sessions]


  @router.post("", response_model=SessionOut)
  def create_session(body: SessionCreate, db=Depends(get_db)):
      s = RecordingSession(name=body.name, workspace_id=body.workspace_id)
      db.add(s)
      db.commit()
      db.refresh(s)
      return _session_out(s, db)


  @router.get("/{session_id}", response_model=SessionOut)
  def get_session_detail(session_id: int, db=Depends(get_db)):
      s = db.query(RecordingSession).filter(RecordingSession.id == session_id).first()
      if not s:
          raise HTTPException(404, "Session not found")
      return _session_out(s, db)


  @router.delete("/{session_id}")
  def delete_session(session_id: int, db=Depends(get_db)):
      s = db.query(RecordingSession).filter(RecordingSession.id == session_id).first()
      if not s:
          raise HTTPException(404, "Session not found")
      db.delete(s)
      db.commit()
      return {"ok": True}


  @router.post("/{session_id}/start", response_model=SessionOut)
  def start_session(session_id: int, db=Depends(get_db)):
      # Stop any other active session first (only one active at a time)
      db.query(RecordingSession).filter(
          RecordingSession.status == "active"
      ).update({"status": "stopped", "ended_at": datetime.utcnow()})

      s = db.query(RecordingSession).filter(RecordingSession.id == session_id).first()
      if not s:
          raise HTTPException(404, "Session not found")
      s.status = "active"
      s.started_at = datetime.utcnow()
      db.commit()
      db.refresh(s)
      return _session_out(s, db)


  @router.post("/{session_id}/stop", response_model=SessionOut)
  def stop_session(session_id: int, db=Depends(get_db)):
      s = db.query(RecordingSession).filter(RecordingSession.id == session_id).first()
      if not s:
          raise HTTPException(404, "Session not found")
      s.status = "stopped"
      s.ended_at = datetime.utcnow()
      db.commit()
      db.refresh(s)

      # Flush any pending transcripts immediately then run LLM summary in background
      def _finish():
          cancel_batch(session_id)  # flushes remaining unblocked transcripts
          summary = generate_session_summary(session_id)
          inner_db = None
          try:
              from api.db import get_session as _gs, RecordingSession as _RS
              inner_db = _gs()
              inner_db.query(_RS).filter(_RS.id == session_id).update({"summary": summary})
              inner_db.commit()
          except Exception as e:
              import logging
              logging.getLogger(__name__).error(f"Summary save error: {e}")
          finally:
              if inner_db:
                  inner_db.close()

      threading.Thread(target=_finish, daemon=True).start()
      return _session_out(s, db)


  @router.get("/{session_id}/blocks", response_model=list[RagBlockOut])
  def poll_blocks(
      session_id: int,
      after: Optional[str] = None,
      db=Depends(get_db),
  ):
      """Return RAG blocks created after `after` ISO timestamp (exclusive).
      Omit `after` to return all blocks (initial load).
      Each block includes its constituent transcript lines with individual timestamps.
      """
      q = db.query(SessionRagBlock).filter(
          SessionRagBlock.session_id == session_id
      )
      if after:
          try:
              after_dt = datetime.fromisoformat(after)
              q = q.filter(SessionRagBlock.block_end > after_dt)
          except ValueError:
              pass
      blocks = q.order_by(SessionRagBlock.block_start).all()
      return [_block_out(b, db) for b in blocks]


  @router.post("/{session_id}/summarize", response_model=SessionOut)
  def summarize_session(session_id: int, db=Depends(get_db)):
      """Re-run LLM summary (idempotent, synchronous)."""
      s = db.query(RecordingSession).filter(RecordingSession.id == session_id).first()
      if not s:
          raise HTTPException(404, "Session not found")
      summary = generate_session_summary(session_id)
      s.summary = summary
      db.commit()
      db.refresh(s)
      return _session_out(s, db)
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add api/routes/sessions.py
  git commit -m "feat: add sessions REST API (CRUD, start/stop, blocks poll, summarize)"
  ```

---

## Task 4: Hook Transcripts into Session Pipeline

**Files:**
- Modify: `api/main.py`
- Modify: `api/routes/realtime.py`

The hook pattern: when a transcript arrives, if there is an active session, call `save_session_transcript` (in a thread so it never blocks the audio path) and then `schedule_batch` (resets the 10-s countdown).

- [ ] **Step 1: Add sessions router to `api/main.py`**

  At the top of `api/main.py`, add alongside the existing router imports:

  ```python
  from api.routes.sessions import router as sessions_router
  ```

  After `app.include_router(api_keys_router)`, add:

  ```python
  app.include_router(sessions_router)
  ```

- [ ] **Step 2: Hook binary-WebSocket transcript in `api/main.py`**

  In the `@app.websocket("/ws")` handler, find the `if text:` block (around line 111) that calls `save_transcript`. Add the session hook immediately after `logger.info(f"Transcript: {text}")`:

  ```python
                          if text:
                              save_transcript(device_id, text)
                              await manager.publish_sse("transcript", {
                                  "device_id": device_id,
                                  "text": text,
                                  "time": datetime.now(TZ_VN).isoformat(),
                              })
                              logger.info(f"Transcript: {text}")
                              # ── Session RAG hook ──────────────────────────────
                              from api.services.session_service import (
                                  get_active_session_id,
                                  save_session_transcript,
                                  schedule_batch,
                              )
                              import concurrent.futures as _cf
                              _sid = get_active_session_id()
                              if _sid:
                                  _cf.ThreadPoolExecutor(max_workers=1).submit(
                                      save_session_transcript, _sid, device_id, text
                                  )
                                  schedule_batch(_sid)
  ```

- [ ] **Step 3: Hook HTTP transcript endpoint in `api/routes/realtime.py`**

  In `realtime.py`, modify `post_transcript` to add the session hook after the `manager.publish_sse` call:

  ```python
  @router.post("/transcript")
  async def post_transcript(data: TranscriptData):
      save_transcript(data.device_id, data.text)
      await manager.publish_sse("transcript", {
          "device_id": data.device_id,
          "text": data.text,
          "time": datetime.now(TZ_VN).isoformat(),
      })
      # ── Session RAG hook ──────────────────────────────────────────────────────
      from api.services.session_service import (
          get_active_session_id, save_session_transcript, schedule_batch
      )
      import concurrent.futures as _cf
      _sid = get_active_session_id()
      if _sid:
          _cf.ThreadPoolExecutor(max_workers=1).submit(
              save_session_transcript, _sid, data.device_id, data.text
          )
          schedule_batch(_sid)
      return {"status": "ok"}
  ```

  Also add the same hook in `transcribe_audio` (after `save_transcript(device_id, text)`):

  ```python
      if text:
          save_transcript(device_id, text)
          await manager.publish_sse("transcript", {
              "device_id": device_id,
              "text": text,
              "time": datetime.now(TZ_VN).isoformat(),
          })
          # ── Session RAG hook ──────────────────────────────────────────────────
          from api.services.session_service import (
              get_active_session_id, save_session_transcript, schedule_batch
          )
          import concurrent.futures as _cf
          _sid = get_active_session_id()
          if _sid:
              _cf.ThreadPoolExecutor(max_workers=1).submit(
                  save_session_transcript, _sid, device_id, text
              )
              schedule_batch(_sid)
  ```

- [ ] **Step 4: Verify endpoint is live**

  ```bash
  curl http://localhost:8000/api/sessions
  ```
  Expected: `[]`

- [ ] **Step 5: Commit**

  ```bash
  git add api/main.py api/routes/realtime.py
  git commit -m "feat: hook transcript saves into session batch aggregator"
  ```

---

## Task 5: TypeScript Types + API Client

**Files:**
- Modify: `web/src/types/index.ts`
- Modify: `web/src/api/client.ts`

- [ ] **Step 1: Append to `web/src/types/index.ts`**

  ```typescript
  export interface RagResult {
    id: number
    doc_id: number
    filename: string
    text: string
    context: string
    category: string
    page_num: number
    bbox: number[]
    score: number
  }

  export interface TranscriptLine {
    id: number
    device_id: string
    text: string
    timestamp: string   // ISO
  }

  export interface SessionRagBlock {
    id: number
    session_id: number
    block_start: string   // ISO — earliest transcript in window
    block_end: string     // ISO — latest transcript in window
    combined_text: string // all transcript text joined
    rag_results: RagResult[]
    transcripts: TranscriptLine[]  // individual timestamped lines
  }

  export interface RecordingSession {
    id: number
    name: string
    workspace_id: number | null
    workspace_name: string | null
    status: "idle" | "active" | "stopped"
    created_at: string
    started_at: string | null
    ended_at: string | null
    summary: string | null
    block_count: number
    transcript_count: number
  }
  ```

- [ ] **Step 2: Update import in `web/src/api/client.ts`**

  Replace the existing import line at the top:

  ```typescript
  import type { Chunk, DocImage, Document, Workspace, Formula, OcrPageData, ApiKey, SearchResult, RecordingSession, SessionRagBlock } from "@/types"
  ```

- [ ] **Step 3: Add `sessions` to the `api` object in `client.ts`**

  Add this block inside the `api` object (after `realtime: { ... },`):

  ```typescript
    sessions: {
      list: () => request<RecordingSession[]>("/api/sessions"),
      create: (name: string, workspace_id: number | null) =>
        request<RecordingSession>("/api/sessions", {
          method: "POST",
          body: JSON.stringify({ name, workspace_id }),
        }),
      get: (id: number) => request<RecordingSession>(`/api/sessions/${id}`),
      delete: (id: number) =>
        request<{ ok: boolean }>(`/api/sessions/${id}`, { method: "DELETE" }),
      start: (id: number) =>
        request<RecordingSession>(`/api/sessions/${id}/start`, { method: "POST" }),
      stop: (id: number) =>
        request<RecordingSession>(`/api/sessions/${id}/stop`, { method: "POST" }),
      blocks: (id: number, after?: string) =>
        request<SessionRagBlock[]>(
          `/api/sessions/${id}/blocks${after ? `?after=${encodeURIComponent(after)}` : ""}`
        ),
      summarize: (id: number) =>
        request<RecordingSession>(`/api/sessions/${id}/summarize`, { method: "POST" }),
    },
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add web/src/types/index.ts web/src/api/client.ts
  git commit -m "feat: add SessionRagBlock/RecordingSession types and api.sessions client"
  ```

---

## Task 6: Sessions List Page

**Files:**
- Create: `web/src/pages/sessions-page.tsx`

- [ ] **Step 1: Create `web/src/pages/sessions-page.tsx`**

  ```tsx
  import { useEffect, useState, useCallback } from "react"
  import { Plus, Radio, Trash2, Play, Clock, BookOpen } from "lucide-react"
  import { Button } from "@/components/ui/button"
  import { Input } from "@/components/ui/input"
  import { Badge } from "@/components/ui/badge"
  import {
    Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
  } from "@/components/ui/dialog"
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

    const handleDelete = async (id: number, e: React.MouseEvent) => {
      e.stopPropagation()
      if (!confirm("Delete this session and all its transcripts?")) return
      try {
        await api.sessions.delete(id)
        setSessions(prev => prev.filter(s => s.id !== id))
      } catch (e) {
        alert(e instanceof Error ? e.message : "Delete failed")
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
                    onClick={(e) => handleDelete(s.id, e)}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}

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
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add web/src/pages/sessions-page.tsx
  git commit -m "feat: add SessionsPage (list, create, delete)"
  ```

---

## Task 7: Session Detail Page

**Files:**
- Create: `web/src/pages/session-detail-page.tsx`

The layout is a **split view**:
- **Left panel (320 px)** — scrollable list of RAG blocks. Each block is a card showing:
  - Time range badge (`08:12:03 – 08:12:13`)
  - Individual transcript lines with their timestamps (`08:12:03 "the methodology section"`, `08:12:06 "uses a control group"`)
  - Chip showing number of RAG matches
- **Right panel** — for the selected block, shows:
  - The full combined text at the top
  - Tabs/list of up to 5 RAG results; selecting one shows:
    - Page image (`api.extract.pageImageUrl(doc_id, page_num)`)
    - Breadcrumb context (`Title > Section > text`)
    - Matched text excerpt
- **Bottom bar** (visible after session is stopped) — LLM summary with markdown rendering

- [ ] **Step 1: Create `web/src/pages/session-detail-page.tsx`**

  ```tsx
  import { useEffect, useState, useCallback, useRef } from "react"
  import {
    Radio, Square, ArrowLeft, Loader2, RefreshCw,
    FileText, BookOpen, ChevronRight, Sparkles, Clock,
  } from "lucide-react"
  import { Button } from "@/components/ui/button"
  import { Badge } from "@/components/ui/badge"
  import { ScrollArea } from "@/components/ui/scroll-area"
  import { api } from "@/api/client"
  import type { RecordingSession, SessionRagBlock, RagResult } from "@/types"

  interface SessionDetailPageProps {
    session: RecordingSession
    onBack: () => void
    onSessionUpdated: (s: RecordingSession) => void
  }

  export function SessionDetailPage({
    session: initialSession,
    onBack,
    onSessionUpdated,
  }: SessionDetailPageProps) {
    const [session, setSession] = useState(initialSession)
    const [blocks, setBlocks] = useState<SessionRagBlock[]>([])
    const [selectedBlockId, setSelectedBlockId] = useState<number | null>(null)
    const [actionLoading, setActionLoading] = useState(false)
    const [summarizing, setSummarizing] = useState(false)
    const lastBlockEndRef = useRef<string | undefined>(undefined)
    const pollRef = useRef<number | null>(null)

    // Initial load — all blocks
    const loadAll = useCallback(async () => {
      const data = await api.sessions.blocks(session.id)
      setBlocks(data)
      if (data.length > 0) {
        lastBlockEndRef.current = data[data.length - 1].block_end
        setSelectedBlockId(data[data.length - 1].id)
      }
    }, [session.id])

    useEffect(() => { loadAll() }, [loadAll])

    // Poll every 5 s when active
    useEffect(() => {
      if (session.status !== "active") {
        if (pollRef.current) clearInterval(pollRef.current)
        return
      }
      pollRef.current = window.setInterval(async () => {
        try {
          const newBlocks = await api.sessions.blocks(session.id, lastBlockEndRef.current)
          if (newBlocks.length > 0) {
            setBlocks(prev => [...prev, ...newBlocks])
            lastBlockEndRef.current = newBlocks[newBlocks.length - 1].block_end
            setSelectedBlockId(newBlocks[newBlocks.length - 1].id)
          }
        } catch (e) {
          console.error("Poll error:", e)
        }
      }, 5000)
      return () => { if (pollRef.current) clearInterval(pollRef.current) }
    }, [session.id, session.status])

    const handleStart = async () => {
      setActionLoading(true)
      try {
        const updated = await api.sessions.start(session.id)
        setSession(updated)
        onSessionUpdated(updated)
      } finally {
        setActionLoading(false)
      }
    }

    const handleStop = async () => {
      setActionLoading(true)
      setSummarizing(true)
      try {
        const updated = await api.sessions.stop(session.id)
        setSession(updated)
        onSessionUpdated(updated)
        // Poll for summary (background thread on server)
        const poll = async () => {
          const refreshed = await api.sessions.get(session.id)
          if (refreshed.summary) {
            setSession(refreshed)
            onSessionUpdated(refreshed)
            setSummarizing(false)
          } else {
            setTimeout(poll, 3000)
          }
        }
        setTimeout(poll, 3000)
      } finally {
        setActionLoading(false)
      }
    }

    const handleResummarize = async () => {
      setSummarizing(true)
      try {
        const updated = await api.sessions.summarize(session.id)
        setSession(updated)
        onSessionUpdated(updated)
      } finally {
        setSummarizing(false)
      }
    }

    const selectedBlock = blocks.find(b => b.id === selectedBlockId) ?? null

    return (
      <div className="flex flex-col h-full">
        {/* ── Toolbar ─────────────────────────────────────────────────────── */}
        <div className="flex items-center gap-2 px-3 py-2 border-b shrink-0 flex-wrap">
          <Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground shrink-0"
            onClick={onBack}>
            <ArrowLeft className="h-4 w-4" /> Back
          </Button>
          <div className="w-px h-4 bg-border shrink-0" />
          <span className="font-medium text-sm truncate">{session.name}</span>
          {session.workspace_name && (
            <Badge variant="outline" className="gap-1 text-xs shrink-0">
              <BookOpen className="h-3 w-3" /> {session.workspace_name}
            </Badge>
          )}
          <Badge
            variant={session.status === "active" ? "default" : "secondary"}
            className="shrink-0"
          >
            {session.status === "active" && (
              <Radio className="h-3 w-3 mr-1 animate-pulse" />
            )}
            {session.status}
          </Badge>
          <div className="ml-auto flex items-center gap-2">
            {session.status === "idle" && (
              <Button size="sm" onClick={handleStart} disabled={actionLoading} className="gap-1.5">
                <Radio className="h-3.5 w-3.5" />
                {actionLoading ? "Starting…" : "Start Recording"}
              </Button>
            )}
            {session.status === "active" && (
              <Button size="sm" variant="destructive" onClick={handleStop}
                disabled={actionLoading} className="gap-1.5">
                <Square className="h-3.5 w-3.5" />
                {actionLoading ? "Stopping…" : "Stop"}
              </Button>
            )}
            {session.status === "stopped" && (
              <Button size="sm" variant="outline" onClick={handleResummarize}
                disabled={summarizing} className="gap-1.5">
                <Sparkles className="h-3.5 w-3.5" />
                {summarizing ? "Summarizing…" : "Re-summarize"}
              </Button>
            )}
          </div>
        </div>

        {/* ── Split view ──────────────────────────────────────────────────── */}
        <div className="flex flex-1 min-h-0 overflow-hidden">
          {/* Left: RAG block list */}
          <div className="w-80 shrink-0 border-r flex flex-col">
            <div className="px-3 py-2 text-xs font-medium text-muted-foreground border-b shrink-0 flex items-center gap-2">
              BLOCKS ({blocks.length})
              {session.status === "active" && (
                <span className="flex items-center gap-1 text-green-500 ml-auto">
                  <RefreshCw className="h-3 w-3 animate-spin" /> live
                </span>
              )}
            </div>
            <ScrollArea className="flex-1">
              {blocks.length === 0 ? (
                <div className="p-4 text-xs text-muted-foreground text-center">
                  {session.status === "active"
                    ? "Waiting for speech… (10 s window)"
                    : "No blocks in this session."}
                </div>
              ) : (
                <div className="flex flex-col">
                  {[...blocks].reverse().map(b => (
                    <BlockCard
                      key={b.id}
                      block={b}
                      selected={selectedBlockId === b.id}
                      onClick={() => setSelectedBlockId(b.id)}
                    />
                  ))}
                </div>
              )}
            </ScrollArea>
          </div>

          {/* Right: RAG context for selected block */}
          <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
            {selectedBlock ? (
              <RagPanel block={selectedBlock} />
            ) : (
              <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
                Select a block to see matched document sections
              </div>
            )}
          </div>
        </div>

        {/* ── Summary ─────────────────────────────────────────────────────── */}
        {session.status === "stopped" && (
          <div className="border-t shrink-0 max-h-64 overflow-y-auto bg-muted/20">
            <div className="px-4 py-2 text-xs font-medium text-muted-foreground flex items-center gap-2 border-b">
              <Sparkles className="h-3.5 w-3.5" /> SESSION SUMMARY
            </div>
            {summarizing ? (
              <div className="px-4 py-3 flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" /> Generating summary…
              </div>
            ) : session.summary ? (
              <div className="px-4 py-3 text-sm whitespace-pre-wrap leading-relaxed">
                {session.summary}
              </div>
            ) : (
              <div className="px-4 py-3 text-sm text-muted-foreground">
                No summary yet.
              </div>
            )}
          </div>
        )}
      </div>
    )
  }


  // ── Block Card (left panel) ───────────────────────────────────────────────────

  function BlockCard({
    block,
    selected,
    onClick,
  }: { block: SessionRagBlock; selected: boolean; onClick: () => void }) {
    const start = new Date(block.block_start).toLocaleTimeString()
    const end = new Date(block.block_end).toLocaleTimeString()
    return (
      <button
        onClick={onClick}
        className={`text-left w-full px-3 py-3 border-b last:border-0 transition-colors hover:bg-muted/50 ${
          selected ? "bg-muted" : ""
        }`}
      >
        {/* Time range */}
        <div className="flex items-center gap-1.5 mb-1.5">
          <Clock className="h-3 w-3 text-muted-foreground shrink-0" />
          <span className="text-[10px] text-muted-foreground">
            {start} – {end}
          </span>
          {block.rag_results.length > 0 && (
            <Badge variant="secondary" className="ml-auto text-[10px] h-4 px-1">
              {block.rag_results.length} match{block.rag_results.length !== 1 ? "es" : ""}
            </Badge>
          )}
        </div>
        {/* Individual transcript lines */}
        <div className="flex flex-col gap-0.5">
          {block.transcripts.map(t => (
            <div key={t.id} className="flex gap-1.5 items-baseline">
              <span className="text-[9px] text-muted-foreground shrink-0 tabular-nums">
                {new Date(t.timestamp).toLocaleTimeString()}
              </span>
              <span className="text-xs leading-snug line-clamp-2">{t.text}</span>
            </div>
          ))}
        </div>
      </button>
    )
  }


  // ── RAG Panel (right panel) ───────────────────────────────────────────────────

  function RagPanel({ block }: { block: SessionRagBlock }) {
    const [selectedResult, setSelectedResult] = useState<RagResult | null>(
      block.rag_results[0] ?? null
    )

    useEffect(() => {
      setSelectedResult(block.rag_results[0] ?? null)
    }, [block.id])

    return (
      <div className="flex flex-col h-full">
        {/* Combined text header */}
        <div className="px-4 py-3 border-b bg-muted/20 shrink-0">
          <div className="text-[10px] text-muted-foreground mb-1 flex items-center gap-2">
            <Clock className="h-3 w-3" />
            {new Date(block.block_start).toLocaleTimeString()} –{" "}
            {new Date(block.block_end).toLocaleTimeString()}
            <span className="ml-1">· {block.transcripts.length} line{block.transcripts.length !== 1 ? "s" : ""}</span>
          </div>
          <p className="text-sm leading-relaxed">{block.combined_text}</p>
        </div>

        {block.rag_results.length === 0 ? (
          <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
            No matching document sections found for this block
          </div>
        ) : (
          <div className="flex flex-1 min-h-0 overflow-hidden">
            {/* Result selector list */}
            <div className="w-52 shrink-0 border-r overflow-y-auto">
              {block.rag_results.map(r => (
                <button
                  key={r.id}
                  onClick={() => setSelectedResult(r)}
                  className={`w-full text-left px-3 py-2.5 border-b last:border-0 transition-colors hover:bg-muted/50 ${
                    selectedResult?.id === r.id ? "bg-muted" : ""
                  }`}
                >
                  <div className="flex items-center gap-1 text-[10px] text-muted-foreground mb-0.5">
                    <FileText className="h-3 w-3 shrink-0" />
                    <span className="truncate">{r.filename}</span>
                  </div>
                  <div className="text-[10px] font-medium">p.{r.page_num} · {r.category}</div>
                  <div className="text-[10px] text-muted-foreground mt-0.5">
                    {Math.round(r.score * 100)}% match
                  </div>
                </button>
              ))}
            </div>

            {/* Detail: page image + breadcrumb + text */}
            {selectedResult && (
              <div className="flex-1 min-w-0 overflow-y-auto p-4 flex flex-col gap-3">
                {/* Breadcrumb */}
                <div className="flex items-center gap-1 text-xs text-muted-foreground flex-wrap">
                  {selectedResult.context.split(" > ").map((part, i, arr) => (
                    <span key={i} className="flex items-center gap-1">
                      {i > 0 && <ChevronRight className="h-3 w-3 shrink-0" />}
                      <span className={i === arr.length - 1 ? "text-foreground font-medium" : ""}>
                        {part}
                      </span>
                    </span>
                  ))}
                </div>

                {/* Page image */}
                <div className="rounded-lg overflow-hidden border bg-muted/30">
                  <img
                    src={api.extract.pageImageUrl(selectedResult.doc_id, selectedResult.page_num)}
                    alt={`Page ${selectedResult.page_num} of ${selectedResult.filename}`}
                    className="w-full object-contain max-h-72"
                    onError={(e) => {
                      (e.target as HTMLImageElement).style.display = "none"
                    }}
                  />
                </div>

                {/* Matched text */}
                <div className="text-xs border rounded-lg p-3 bg-muted/20 leading-relaxed">
                  {selectedResult.text}
                </div>

                <div className="text-[10px] text-muted-foreground">
                  Score: {(selectedResult.score * 100).toFixed(1)}% · {selectedResult.filename} p.{selectedResult.page_num}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    )
  }
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add web/src/pages/session-detail-page.tsx
  git commit -m "feat: add SessionDetailPage (block list + RAG split view)"
  ```

---

## Task 8: Sidebar Nav Item

**Files:**
- Modify: `web/src/components/app-sidebar.tsx`

- [ ] **Step 1: Add `Radio` to lucide imports**

  Change the import line:
  ```typescript
  import {
    Database, FolderOpen, BookOpen, ChevronRight,
    Plus, Activity, Settings, Radio,
  } from "lucide-react";
  ```

- [ ] **Step 2: Update `AppSidebarProps` — add `onSelectSessions` and expand `activePage`**

  ```typescript
  interface AppSidebarProps extends React.ComponentProps<typeof Sidebar> {
    activePage: "dataset" | "workspace" | "realtime" | "sessions" | "settings" | null;
    activeWorkspaceId: number | null;
    workspaces: Workspace[];
    workspacesLoading?: boolean;
    onSelectDataset: () => void;
    onSelectWorkspace: (ws: Workspace) => void;
    onSelectRealtime: () => void;
    onSelectSessions: () => void;
    onSelectSettings: () => void;
    onCreateWorkspace: () => void;
    onCreateWorkspaceDialog?: (open: boolean) => void;
  }
  ```

- [ ] **Step 3: Add to function destructuring**

  ```typescript
  export function AppSidebar({
    activePage,
    activeWorkspaceId,
    workspaces,
    onSelectDataset,
    onSelectWorkspace,
    onSelectRealtime,
    onSelectSessions,
    onSelectSettings,
    onCreateWorkspace,
    ...props
  }: AppSidebarProps) {
  ```

- [ ] **Step 4: Add Sessions `SidebarGroup` after the Realtime group**

  ```tsx
        {/* Sessions */}
        <SidebarGroup>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                isActive={activePage === "sessions"}
                onClick={onSelectSessions}
                className="cursor-pointer"
              >
                <Radio className="size-4" />
                <span>Sessions</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroup>
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add web/src/components/app-sidebar.tsx
  git commit -m "feat: add Sessions nav item to sidebar"
  ```

---

## Task 9: Wire Sessions into App.tsx

**Files:**
- Modify: `web/src/App.tsx`

- [ ] **Step 1: Add imports**

  ```typescript
  import { SessionsPage } from "@/pages/sessions-page";
  import { SessionDetailPage } from "@/pages/session-detail-page";
  import type { RecordingSession } from "@/types";
  ```

  Add `Radio` to the lucide import:
  ```typescript
  import { Database, FolderOpen, ArrowLeft, Activity, Wifi, Settings, Radio } from "lucide-react";
  ```

- [ ] **Step 2: Add session state after the existing `activeWorkspace` state**

  ```typescript
  const [selectedSession, setSelectedSession] = useState<RecordingSession | null>(null)
  ```

  Add route flag after the `isSettings` line:
  ```typescript
  const isSessions = location.pathname === "/sessions" || location.pathname.startsWith("/sessions/")
  ```

- [ ] **Step 3: Add session handlers (after `handleWorkspaceDeleted`)**

  ```typescript
  const handleSelectSession = (s: RecordingSession) => {
    setSelectedSession(s)
    navigate(`/sessions/${s.id}`)
  }

  const handleSessionUpdated = (s: RecordingSession) => {
    if (selectedSession?.id === s.id) setSelectedSession(s)
  }
  ```

- [ ] **Step 4: Add session case to the `breadcrumb` computation**

  Add before the final `return [{ icon: <FolderOpen ...` line:

  ```typescript
  if (isSessions) {
    return selectedSession
      ? [
          {
            icon: <Radio className="h-4 w-4" />,
            label: "Sessions",
            onClick: () => { setSelectedSession(null); navigate("/sessions"); },
          },
          { label: selectedSession.name },
        ]
      : [{ icon: <Radio className="h-4 w-4" />, label: "Sessions" }];
  }
  ```

- [ ] **Step 5: Pass `onSelectSessions` to `AppSidebar` and update `activePage`**

  ```tsx
  <AppSidebar
    activePage={
      isRealtime ? "realtime"
      : isSettings ? "settings"
      : isDataset ? "dataset"
      : isWorkspace ? "workspace"
      : isSessions ? "sessions"
      : null
    }
    ...
    onSelectSessions={() => { setSelectedSession(null); navigate("/sessions"); }}
    ...
  />
  ```

- [ ] **Step 6: Add sessions rendering branch in the content area**

  In the `<div className="flex flex-1 overflow-hidden">` block, add before the final `else` workspace branch:

  ```tsx
  ) : isSessions ? (
    selectedSession ? (
      <div className="flex-1 flex flex-col overflow-hidden min-h-0">
        <SessionDetailPage
          session={selectedSession}
          onBack={() => { setSelectedSession(null); navigate("/sessions"); }}
          onSessionUpdated={handleSessionUpdated}
        />
      </div>
    ) : (
      <div className="flex-1 overflow-y-auto">
        <SessionsPage
          workspaces={workspaces}
          onSelectSession={handleSelectSession}
        />
      </div>
    )
  ```

- [ ] **Step 7: Add URL sync for session deep-links (after workspace URL sync `useEffect`)**

  ```typescript
  useEffect(() => {
    const sessionId = location.pathname.match(/^\/sessions\/(\d+)$/)?.[1]
    if (sessionId) {
      api.sessions.get(parseInt(sessionId))
        .then(s => setSelectedSession(s))
        .catch(() => navigate("/sessions"))
    }
  }, [location.pathname])
  ```

- [ ] **Step 8: Add routes in `App()` return**

  ```tsx
  <Route path="/sessions" element={<AppContent />} />
  <Route path="/sessions/:id" element={<AppContent />} />
  ```

- [ ] **Step 9: Commit**

  ```bash
  git add web/src/App.tsx
  git commit -m "feat: wire Sessions pages into App routing and sidebar nav"
  ```

---

## Task 10: End-to-End Smoke Test

- [ ] **Step 1: Verify backend endpoints**

  ```bash
  # All sessions (empty)
  curl -s http://localhost:8000/api/sessions | python3 -m json.tool
  # Expected: []

  # Create session linked to workspace 1
  curl -s -X POST http://localhost:8000/api/sessions \
    -H "Content-Type: application/json" \
    -d '{"name":"Smoke Test","workspace_id":1}' | python3 -m json.tool
  # Expected: {id:1, status:"idle", block_count:0, ...}

  # Start it
  curl -s -X POST http://localhost:8000/api/sessions/1/start | python3 -m json.tool
  # Expected: status:"active"

  # Send 3 transcripts quickly
  for i in 1 2 3; do
    curl -s -X POST http://localhost:8000/api/realtime/transcript \
      -H "Content-Type: application/json" \
      -d "{\"device_id\":\"esp32-001\",\"text\":\"Test sentence $i about the document\"}"
  done

  # Wait 12 s for batch to fire
  sleep 12

  # Check blocks
  curl -s http://localhost:8000/api/sessions/1/blocks | python3 -m json.tool
  # Expected: 1 block, combined_text has all 3 sentences,
  #           transcripts has 3 lines, rag_results populated (if workspace has docs)

  # Stop (triggers flush + LLM summary)
  curl -s -X POST http://localhost:8000/api/sessions/1/stop | python3 -m json.tool

  # Poll for summary (wait ~10 s then re-GET)
  sleep 10
  curl -s http://localhost:8000/api/sessions/1 | python3 -m json.tool
  # Expected: summary field populated
  ```

- [ ] **Step 2: Verify frontend**

  ```bash
  cd /Users/tuantran/WorkSpace/process_documents/web
  npm run dev
  ```

  Open browser and verify:
  1. "Sessions" appears in sidebar — click it → empty sessions list
  2. "New Session" → create with a workspace → dialog closes, navigates to detail
  3. "Start Recording" → status badge turns green "active", "live" indicator in left panel
  4. Send transcript via curl or Real-time Monitor upload → after 10 s a block card appears in left panel
  5. Each block shows time range + individual lines with timestamps
  6. Click block → right panel shows page image + breadcrumb + matched text
  7. Click different RAG results in the right sub-list → page image changes
  8. "Stop" → summary bar appears at bottom, "Generating summary…" → text appears
  9. Navigate away and back → URL `/sessions/1` restores the detail page correctly

- [ ] **Step 3: Final commit**

  ```bash
  git add -A
  git commit -m "feat: complete recording session + RAG batch pipeline"
  ```

---

## Self-Review

**Spec coverage:**
- ✅ User creates session, selects workspace
- ✅ Start / Stop session
- ✅ Individual transcripts saved with timestamps (for display)
- ✅ 10-second batching: multiple transcripts combined → single RAG query per window
- ✅ Timer resets on each transcript arrival (debounced) — fires after 10 s of silence
- ✅ On Stop: any pending unbatched transcripts flushed immediately before summary
- ✅ Left panel: block cards showing time range + individual timestamped lines
- ✅ Right panel: page image + breadcrumb + matched text for selected block
- ✅ Up to 5 RAG results per block, selectable
- ✅ End-of-session LLM summary over all blocks (in background thread)
- ✅ Summary shown at bottom when session is stopped
- ✅ Persisted in DB — sessions browsable after refresh

**Placeholder scan:** None — all code is complete.

**Type consistency:**
- `SessionRagBlock.transcripts: TranscriptLine[]` defined in Task 5, populated by `_block_out()` in Task 3, rendered in `BlockCard` in Task 7 ✅
- `RagResult` used identically in types (Task 5), service (Task 2), routes (Task 3), and UI (Task 7) ✅
- `RecordingSession.status` is `"idle" | "active" | "stopped"` in types (Task 5) matching DB default `"idle"` (Task 1) ✅
- `api.sessions.blocks(id, after?)` returns `SessionRagBlock[]` — matches usage in `SessionDetailPage` (Task 7) ✅
- `api.extract.pageImageUrl(doc_id, page_num)` exists at `client.ts:87` ✅
