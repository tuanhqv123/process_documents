"""
SQLAlchemy database with PostgreSQL + pgvector.
"""

import os
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, ForeignKey, DateTime, text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from pgvector.sqlalchemy import Vector

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/pdf_processor"
)

EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))

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
    status = Column(String, default="pending")
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

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
    embedding = Column(Vector(384), nullable=True)

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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.create_all(bind=engine)


def get_session():
    return SessionLocal()
