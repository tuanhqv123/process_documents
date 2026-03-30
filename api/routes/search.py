from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import text

from api.db import get_session, Chunk, Document, WorkspaceDoc
from api.embedding_client import embedding_client

router = APIRouter(prefix="/api/workspaces", tags=["search"])


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    min_score: float = 0.0


class SearchResult(BaseModel):
    id: int
    doc_id: int
    filename: str
    text: str
    page_start: int
    page_end: int
    score: float


def _get_db():
    db = get_session()
    try:
        yield db
    finally:
        db.close()


@router.post("/{ws_id}/search", response_model=list[SearchResult])
def search_workspace(ws_id: int, body: SearchRequest, db= Depends(_get_db)):
    ws = db.execute(
        text("SELECT 1 FROM workspaces WHERE id = :id"),
        {"id": ws_id}
    ).first()
    if not ws:
        raise HTTPException(404, "Workspace not found")

    try:
        query_embedding = embedding_client.embed_single(body.query)
    except Exception as e:
        raise HTTPException(503, f"Embedding service unavailable: {e}")

    results = db.execute(
        text("""
            SELECT c.id, c.doc_id, d.filename, c.text, c.page_start, c.page_end,
                   1 - (c.embedding <=> :query_embedding) AS score
            FROM chunks c
            JOIN documents d ON d.id = c.doc_id
            JOIN workspace_docs wd ON wd.doc_id = c.doc_id
            WHERE wd.workspace_id = :ws_id
              AND c.embedding IS NOT NULL
              AND (1 - (c.embedding <=> :query_embedding)) >= :min_score
            ORDER BY c.embedding <=> :query_embedding
            LIMIT :top_k
        """),
        {"query_embedding": str(query_embedding), "ws_id": ws_id, "top_k": body.top_k, "min_score": body.min_score}
    ).fetchall()

    return [
        SearchResult(
            id=r[0],
            doc_id=r[1],
            filename=r[2],
            text=r[3],
            page_start=r[4],
            page_end=r[5],
            score=float(r[6]),
        )
        for r in results
    ]
