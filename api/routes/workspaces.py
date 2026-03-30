"""Workspace routes: CRUD + document membership."""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from api.db import get_session, Workspace, WorkspaceDoc, Document
from api.models import WorkspaceCreate, WorkspaceOut, DocumentOut, AddDocToWorkspace
from api.routes.documents import _doc_model

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


def _get_db():
    db = get_session()
    try:
        yield db
    finally:
        db.close()


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(db: Session = Depends(_get_db)):
    workspaces = db.query(Workspace).order_by(Workspace.created_at.desc()).all()
    result = []
    for ws in workspaces:
        doc_count = db.query(WorkspaceDoc).filter(WorkspaceDoc.workspace_id == ws.id).count()
        result.append(WorkspaceOut(
            id=ws.id,
            name=ws.name,
            description=ws.description or "",
            created_at=ws.created_at.isoformat() if ws.created_at else "",
            doc_count=doc_count,
        ))
    return result


@router.post("", response_model=WorkspaceOut)
def create_workspace(body: WorkspaceCreate, db: Session = Depends(_get_db)):
    ws = Workspace(
        name=body.name,
        description=body.description,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return WorkspaceOut(
        id=ws.id,
        name=ws.name,
        description=ws.description or "",
        created_at=ws.created_at.isoformat() if ws.created_at else "",
        doc_count=0,
    )


@router.delete("/{ws_id}")
def delete_workspace(ws_id: int, db: Session = Depends(_get_db)):
    ws = db.query(Workspace).filter(Workspace.id == ws_id).first()
    if not ws:
        raise HTTPException(404, "Workspace not found")
    db.delete(ws)
    db.commit()
    return {"ok": True}


@router.get("/{ws_id}/documents", response_model=list[DocumentOut])
def get_workspace_documents(ws_id: int, db: Session = Depends(_get_db)):
    ws = db.query(Workspace).filter(Workspace.id == ws_id).first()
    if not ws:
        raise HTTPException(404, "Workspace not found")
    ws_docs = db.query(WorkspaceDoc).filter(WorkspaceDoc.workspace_id == ws_id).all()
    doc_ids = [wd.doc_id for wd in ws_docs]
    docs = db.query(Document).filter(Document.id.in_(doc_ids)).order_by(Document.created_at.desc()).all()
    return [_doc_model(d) for d in docs]


@router.post("/{ws_id}/documents")
def add_document(ws_id: int, body: AddDocToWorkspace, db: Session = Depends(_get_db)):
    ws = db.query(Workspace).filter(Workspace.id == ws_id).first()
    if not ws:
        raise HTTPException(404, "Workspace not found")
    doc = db.query(Document).filter(Document.id == body.doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    
    existing = db.query(WorkspaceDoc).filter(
        WorkspaceDoc.workspace_id == ws_id,
        WorkspaceDoc.doc_id == body.doc_id
    ).first()
    if not existing:
        wd = WorkspaceDoc(workspace_id=ws_id, doc_id=body.doc_id)
        db.add(wd)
        db.commit()
    return {"ok": True}


@router.delete("/{ws_id}/documents/{doc_id}")
def remove_document(ws_id: int, doc_id: int, db: Session = Depends(_get_db)):
    ws = db.query(Workspace).filter(Workspace.id == ws_id).first()
    if not ws:
        raise HTTPException(404, "Workspace not found")
    wd = db.query(WorkspaceDoc).filter(
        WorkspaceDoc.workspace_id == ws_id,
        WorkspaceDoc.doc_id == doc_id
    ).first()
    if wd:
        db.delete(wd)
        db.commit()
    return {"ok": True}
