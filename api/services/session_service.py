"""Session service: per-transcript save, 10-s RAG batch aggregator, LLM summary."""

import json
import logging
import threading
from datetime import datetime

from sqlalchemy import text as sql_text

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
            sql_text("SELECT id FROM recording_sessions WHERE status = 'active' LIMIT 1")
        ).first()
        return row[0] if row else None
    finally:
        db.close()


# ── Save individual transcript ────────────────────────────────────────────────

def save_session_transcript(session_id: int, device_id: str, content: str) -> None:
    """Insert one SessionTranscript row (block_id=NULL — aggregator fills it later)."""
    db = get_session()
    try:
        t = SessionTranscript(
            session_id=session_id,
            device_id=device_id,
            text=content,
            created_at=datetime.utcnow(),
        )
        db.add(t)
        db.commit()
    except Exception as e:
        logger.error(f"save_session_transcript error: {e}")
        db.rollback()
    finally:
        db.close()


# ── 10-second batch aggregator ────────────────────────────────────────────────

_batch_timers: dict[int, threading.Timer] = {}
_timer_lock = threading.Lock()
BATCH_SECONDS = 10


def schedule_batch(session_id: int) -> None:
    """Cancel any existing timer and schedule a fresh 10-s countdown.

    Called every time a transcript arrives. After BATCH_SECONDS of silence
    the timer fires and flushes pending transcripts into a RAG block.
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
    _flush_batch(session_id)


def _flush_batch(session_id: int) -> None:
    """Collect unblocked transcripts, run RAG on combined text, create a SessionRagBlock."""
    with _timer_lock:
        _batch_timers.pop(session_id, None)
    db = get_session()
    try:
        session = db.query(RecordingSession).filter(
            RecordingSession.id == session_id
        ).first()
        if not session:
            return

        pending = (
            db.query(SessionTranscript)
            .filter(
                SessionTranscript.session_id == session_id,
                SessionTranscript.block_id == None,  # noqa: E711
            )
            .order_by(SessionTranscript.created_at)
            .all()
        )
        if not pending:
            return

        combined_text = " ".join(t.text for t in pending)
        block_start = pending[0].created_at
        block_end = pending[-1].created_at

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
        db.flush()

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
    """Embed query and search workspace leaf nodes. Returns list of result dicts."""
    from api.embedding_client import embedding_client

    try:
        q_emb = embedding_client.embed_single(query)
    except Exception as e:
        logger.warning(f"Embedding unavailable: {e}")
        return []

    rows = db.execute(
        sql_text("""
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
            sql_text("""
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
    """Build prompt from all RAG blocks, call the active LLM, return summary text."""
    db = get_session()
    prompt = ""
    try:
        session = db.query(RecordingSession).filter(
            RecordingSession.id == session_id
        ).first()
        if not session:
            return ""

        ws_row = db.execute(
            sql_text("SELECT name FROM workspaces WHERE id = :id"),
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
            for match in rag[:3]:
                lines.append(
                    f"  → \"{match['filename']}\" p.{match['page_num']}: {match['context']}"
                )
            lines.append("")

        prompt = "\n".join(lines) + (
            "\nWrite a concise session summary covering:\n"
            "1. What the user discussed and asked about\n"
            "2. Which document sections were most relevant\n"
            "3. Key insights from the session\n\n"
            "Use markdown with headers."
        )
    except Exception as e:
        logger.error(f"generate_session_summary DB error: {e}")
        return f"Summary generation failed: {e}"
    finally:
        db.close()

    if not prompt:
        return "No transcript data was recorded in this session."

    try:
        return _call_llm(prompt)
    except Exception as e:
        logger.error(f"_call_llm error: {e}")
        return f"LLM call failed: {e}"


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
