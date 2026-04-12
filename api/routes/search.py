from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import text

from api.db import get_session
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
    context: str          # "Title > Section > text"
    category: str
    page_num: int
    bbox: list[float]
    score: float


def _get_db():
    db = get_session()
    try:
        yield db
    finally:
        db.close()


@router.post("/{ws_id}/search", response_model=list[SearchResult])
def search_workspace(ws_id: int, body: SearchRequest, db=Depends(_get_db)):
    ws = db.execute(text("SELECT 1 FROM workspaces WHERE id = :id"), {"id": ws_id}).first()
    if not ws:
        raise HTTPException(404, "Workspace not found")

    try:
        query_embedding = embedding_client.embed_single(body.query)
    except Exception as e:
        raise HTTPException(503, f"Embedding service unavailable: {e}")

    # Vector search on leaf nodes (node_rank=3) across documents in this workspace
    rows = db.execute(
        text("""
            SELECT
                n.id,
                n.doc_id,
                d.filename,
                n.text,
                n.category,
                n.page_num,
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
              AND (1 - (n.embedding <=> CAST(:qemb AS vector))) >= :min_score
            ORDER BY n.embedding <=> CAST(:qemb AS vector)
            LIMIT :top_k
        """),
        {
            "qemb": str(query_embedding),
            "ws_id": ws_id,
            "top_k": body.top_k,
            "min_score": body.min_score,
        },
    ).fetchall()

    if not rows:
        return []

    # For each result, fetch its structural ancestors (Title, Section-header)
    # to build the context breadcrumb
    results = []
    for r in rows:
        node_id, doc_id, filename, node_text, category, page_num, bbox, path, score = r

        # Get ancestor titles/sections via ltree
        ancestors = db.execute(
            text("""
                SELECT category, text
                FROM document_nodes
                WHERE CAST(path AS ltree) @> CAST(:node_path AS ltree)
                  AND path != :node_path
                  AND category IN ('Title', 'Section-header')
                  AND text != ''
                ORDER BY depth ASC
            """),
            {"node_path": path},
        ).fetchall()

        breadcrumb_parts = [a.text for a in ancestors if a.text]
        if node_text:
            breadcrumb_parts.append(node_text)
        context = " > ".join(breadcrumb_parts)

        results.append(
            SearchResult(
                id=node_id,
                doc_id=doc_id,
                filename=filename,
                text=node_text or "",
                context=context,
                category=category,
                page_num=page_num or 0,
                bbox=list(bbox) if bbox else [],
                score=float(score),
            )
        )

    return results
