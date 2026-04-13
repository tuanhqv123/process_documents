"""
SQLAlchemy database with PostgreSQL + pgvector.
"""

import os
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, Float, ForeignKey, DateTime, text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/pdf_processor"
)

EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_size = Column(Integer, default=0)
    page_count = Column(Integer, default=0)
    image_count = Column(Integer, default=0)
    chunk_count = Column(Integer, default=0)
    formula_count = Column(Integer, default=0)
    # Status: uploaded → extracting → extracted → ready | error
    status = Column(String, default="uploaded")
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # OCR extraction progress fields
    extract_progress = Column(Integer, default=0)       # 0-100 percent
    extract_message = Column(Text, nullable=True)       # status message
    extracted_pages = Column(Integer, default=0)        # pages done
    total_pages_ocr = Column(Integer, default=0)        # total pages for OCR
    ocr_data_path = Column(String, nullable=True)       # path to OCR JSON file

    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")
    images = relationship("DocImage", back_populates="document", cascade="all, delete-orphan")
    formulas = relationship("Formula", back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    page_start = Column(Integer, default=0)
    page_end = Column(Integer, default=0)
    section_path = Column(Text, default="[]")
    element_types = Column(Text, default="[]")
    html = Column(Text, default="")
    is_edited = Column(Boolean, default=False)
    embedding = Column(Vector(EMBEDDING_DIM), nullable=True)

    document = relationship("Document", back_populates="chunks")


class DocImage(Base):
    __tablename__ = "doc_images"

    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    page_num = Column(Integer, default=0)
    image_path = Column(String, nullable=False)
    image_type = Column(String, default="generic")
    ocr_text = Column(Text, default="")
    nearby_text = Column(Text, default="")
    bbox = Column(Text, default="[]")
    is_edited = Column(Boolean, default=False)

    document = relationship("Document", back_populates="images")


class Formula(Base):
    __tablename__ = "formulas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    page_num = Column(Integer, default=0)
    latex = Column(Text, nullable=False)
    formula_type = Column(String, default="display")
    bbox = Column(Text, default="[]")
    is_edited = Column(Boolean, default=False)

    document = relationship("Document", back_populates="formulas")


class DocumentNode(Base):
    """Hierarchical knowledge graph node extracted from OCR layout analysis.

    Tree structure (stored as adjacency list + ltree path):
        Document (root)
        └── Title              rank=1
            └── Section-header rank=2
                ├── Text        leaf
                ├── Table       leaf
                └── Picture     leaf

    The ltree `path` column enables fast ancestor/subtree queries:
        SELECT * FROM document_nodes WHERE path <@ 'doc1.node5'   -- subtree of node5
        SELECT * FROM document_nodes WHERE path @> 'doc1.n5.n12'  -- ancestors of n12
    """
    __tablename__ = "document_nodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id = Column(Integer, ForeignKey("document_nodes.id", ondelete="CASCADE"), nullable=True)

    # OCR layout fields
    category = Column(String, nullable=False)      # Title, Section-header, Text, Table, Picture …
    text = Column(Text, default="")
    plain_text = Column(Text, default="")          # clean plain-text version for embedding
    page_num = Column(Integer, default=0)          # 1-based page number
    bbox = Column(ARRAY(Float), nullable=True)     # [x1, y1, x2, y2]
    position = Column(Integer, default=0)          # reading order index within parent

    # Hierarchy metadata
    node_rank = Column(Integer, default=3)         # 0=document root, 1=title, 2=section, 3=leaf
    depth = Column(Integer, default=0)             # depth in tree (0 = root)
    path = Column(Text, nullable=True)             # ltree path string e.g. "1.23.45"

    # Semantic embedding (for leaf nodes)
    embedding = Column(Vector(EMBEDDING_DIM), nullable=True)

    # Self-referential tree — build tree via flat query in knowledge_graph.py
    # (avoids complex bidirectional ORM setup for self-referential adjacency lists)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    label = Column(String, nullable=False)
    type = Column(String, nullable=False, default="ocr")  # "ocr" | "llm"
    base_url = Column(String, nullable=False)
    api_key = Column(String, nullable=False, default="")  # stored, never returned to frontend
    model_name = Column(String, nullable=False, default="")
    is_active = Column(Boolean, default=False)  # one active per type
    created_at = Column(DateTime, default=datetime.utcnow)


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class WorkspaceDoc(Base):
    __tablename__ = "workspace_docs"

    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    doc_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)


class RecordingSession(Base):
    """A recording session. status: idle → active → stopped. summary populated at session end."""
    __tablename__ = "recording_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True)
    status = Column(String, default="idle")   # idle | active | stopped
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    summary = Column(Text, nullable=True)     # LLM-generated summary at session end

    transcripts = relationship("SessionTranscript", back_populates="session", cascade="all, delete-orphan")
    rag_blocks = relationship("SessionRagBlock", back_populates="session", cascade="all, delete-orphan")


class SessionTranscript(Base):
    """One row per Whisper chunk (~2 s). Linked to a RAG block once aggregated."""
    __tablename__ = "session_transcripts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("recording_sessions.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    block_id = Column(Integer, ForeignKey("session_rag_blocks.id", ondelete="SET NULL", use_alter=True),
                      nullable=True, index=True)   # NULL until the 10-s batch fires
    device_id = Column(String, nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("RecordingSession", back_populates="transcripts")
    block = relationship("SessionRagBlock", back_populates="transcripts")


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

    session = relationship("RecordingSession", back_populates="rag_blocks")
    transcripts = relationship("SessionTranscript", back_populates="block")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS ltree"))
        conn.commit()
    Base.metadata.create_all(bind=engine)
    # Create ltree GiST index on path column after tables are created
    with engine.connect() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_document_nodes_path "
            "ON document_nodes USING GIST (CAST(path AS ltree))"
        ))
        # Add plain_text column if it doesn't exist yet (idempotent migration)
        conn.execute(text(
            "ALTER TABLE document_nodes ADD COLUMN IF NOT EXISTS plain_text TEXT DEFAULT ''"
        ))
        conn.commit()


def get_session():
    return SessionLocal()
