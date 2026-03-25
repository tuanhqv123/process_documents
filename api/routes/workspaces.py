"""Workspace routes: CRUD + document membership."""

from fastapi import APIRouter, HTTPException

from api import db as database
from api.models import WorkspaceCreate, WorkspaceOut, DocumentOut, AddDocToWorkspace
from api.routes.documents import _doc_row

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces():
    rows = database.list_workspaces()
    result = []
    for r in rows:
        docs = database.get_workspace_documents(r["id"])
        result.append(WorkspaceOut(
            id=r["id"],
            name=r["name"],
            description=r["description"] or "",
            created_at=r["created_at"],
            doc_count=len(docs),
        ))
    return result


@router.post("", response_model=WorkspaceOut)
def create_workspace(body: WorkspaceCreate):
    ws_id = database.insert_workspace(body.name, body.description)
    row = database.get_workspace(ws_id)
    return WorkspaceOut(
        id=row["id"],
        name=row["name"],
        description=row["description"] or "",
        created_at=row["created_at"],
        doc_count=0,
    )


@router.delete("/{ws_id}")
def delete_workspace(ws_id: int):
    if not database.get_workspace(ws_id):
        raise HTTPException(404, "Workspace not found")
    database.delete_workspace(ws_id)
    return {"ok": True}


@router.get("/{ws_id}/documents", response_model=list[DocumentOut])
def get_workspace_documents(ws_id: int):
    if not database.get_workspace(ws_id):
        raise HTTPException(404, "Workspace not found")
    rows = database.get_workspace_documents(ws_id)
    return [_doc_row(r) for r in rows]


@router.post("/{ws_id}/documents")
def add_document(ws_id: int, body: AddDocToWorkspace):
    if not database.get_workspace(ws_id):
        raise HTTPException(404, "Workspace not found")
    if not database.get_document(body.doc_id):
        raise HTTPException(404, "Document not found")
    database.add_doc_to_workspace(ws_id, body.doc_id)
    return {"ok": True}


@router.delete("/{ws_id}/documents/{doc_id}")
def remove_document(ws_id: int, doc_id: int):
    if not database.get_workspace(ws_id):
        raise HTTPException(404, "Workspace not found")
    database.remove_doc_from_workspace(ws_id, doc_id)
    return {"ok": True}
