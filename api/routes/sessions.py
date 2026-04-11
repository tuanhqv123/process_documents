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
    timestamp: str  # ISO — from created_at field


class RagBlockOut(BaseModel):
    id: int
    session_id: int
    block_start: str
    block_end: str
    combined_text: str
    rag_results: list[RagResultOut]
    transcripts: list[TranscriptLineOut]


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
        .order_by(SessionTranscript.created_at)
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
                timestamp=t.created_at.isoformat(),
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
    # Stop any other active session first
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

    # Flush remaining transcripts then generate summary in background thread
    def _finish():
        cancel_batch(session_id)
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
    """Return RAG blocks. If `after` is given (ISO timestamp), return only blocks
    with block_end > after. Each block includes its transcript lines."""
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
    """Re-run LLM summary synchronously (idempotent)."""
    s = db.query(RecordingSession).filter(RecordingSession.id == session_id).first()
    if not s:
        raise HTTPException(404, "Session not found")
    summary = generate_session_summary(session_id)
    s.summary = summary
    db.commit()
    db.refresh(s)
    return _session_out(s, db)
