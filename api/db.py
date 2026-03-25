"""
SQLite database: schema creation and CRUD helpers.
"""

import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "knowledge.db"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with get_conn() as conn:
        # Add file_size column if it doesn't exist (safe migration)
        try:
            conn.execute("ALTER TABLE documents ADD COLUMN file_size INTEGER DEFAULT 0")
        except Exception:
            pass
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            filename    TEXT NOT NULL,
            file_path   TEXT NOT NULL,
            file_size   INTEGER DEFAULT 0,
            page_count  INTEGER DEFAULT 0,
            image_count INTEGER DEFAULT 0,
            chunk_count INTEGER DEFAULT 0,
            status      TEXT DEFAULT 'pending',
            error       TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS chunks (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id        INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            chunk_index   INTEGER NOT NULL,
            text          TEXT NOT NULL,
            page_start    INTEGER DEFAULT 0,
            page_end      INTEGER DEFAULT 0,
            section_path  TEXT DEFAULT '[]',
            element_types TEXT DEFAULT '[]',
            is_edited     INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS doc_images (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id       INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page_num     INTEGER DEFAULT 0,
            image_path   TEXT NOT NULL,
            image_type   TEXT DEFAULT 'generic',
            ocr_text     TEXT DEFAULT '',
            nearby_text  TEXT DEFAULT '',
            is_edited    INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS workspaces (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            description TEXT DEFAULT '',
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS workspace_docs (
            workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            doc_id       INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            PRIMARY KEY (workspace_id, doc_id)
        );
        """)


# ── Documents ──────────────────────────────────────────────────────────────────

def insert_document(filename: str, file_path: str, file_size: int = 0) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO documents (filename, file_path, file_size) VALUES (?, ?, ?)",
            (filename, file_path, file_size),
        )
        return cur.lastrowid


def update_document_status(doc_id: int, status: str, error: str = None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE documents SET status=?, error=? WHERE id=?",
            (status, error, doc_id),
        )


def update_document_counts(doc_id: int, page_count: int, image_count: int, chunk_count: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE documents SET page_count=?, image_count=?, chunk_count=? WHERE id=?",
            (page_count, image_count, chunk_count, doc_id),
        )


def get_document(doc_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()


def list_documents() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()


def delete_document(doc_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))


# ── Chunks ─────────────────────────────────────────────────────────────────────

def insert_chunks(doc_id: int, chunks: list[dict]):
    with get_conn() as conn:
        conn.executemany(
            """INSERT INTO chunks
               (doc_id, chunk_index, text, page_start, page_end, section_path, element_types)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    doc_id,
                    c["chunk_index"],
                    c["text"],
                    c["page_start"],
                    c["page_end"],
                    json.dumps(c.get("section_path", [])),
                    json.dumps(c.get("element_types", [])),
                )
                for c in chunks
            ],
        )


def get_chunks(doc_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM chunks WHERE doc_id=? ORDER BY chunk_index",
            (doc_id,),
        ).fetchall()


def update_chunk_text(chunk_id: int, text: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE chunks SET text=?, is_edited=1 WHERE id=?",
            (text, chunk_id),
        )


# ── Images ─────────────────────────────────────────────────────────────────────

def insert_image(doc_id: int, page_num: int, image_path: str,
                 image_type: str, ocr_text: str, nearby_text: str):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO doc_images
               (doc_id, page_num, image_path, image_type, ocr_text, nearby_text)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (doc_id, page_num, image_path, image_type, ocr_text, nearby_text),
        )


def get_images(doc_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM doc_images WHERE doc_id=? ORDER BY page_num, id",
            (doc_id,),
        ).fetchall()


def update_image_ocr(image_id: int, ocr_text: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE doc_images SET ocr_text=?, is_edited=1 WHERE id=?",
            (ocr_text, image_id),
        )


# ── Workspaces ─────────────────────────────────────────────────────────────────

def insert_workspace(name: str, description: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO workspaces (name, description) VALUES (?, ?)",
            (name, description),
        )
        return cur.lastrowid


def list_workspaces() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM workspaces ORDER BY created_at DESC").fetchall()


def get_workspace(ws_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM workspaces WHERE id=?", (ws_id,)).fetchone()


def delete_workspace(ws_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM workspaces WHERE id=?", (ws_id,))


def add_doc_to_workspace(ws_id: int, doc_id: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO workspace_docs (workspace_id, doc_id) VALUES (?, ?)",
            (ws_id, doc_id),
        )


def remove_doc_from_workspace(ws_id: int, doc_id: int):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM workspace_docs WHERE workspace_id=? AND doc_id=?",
            (ws_id, doc_id),
        )


def get_document_workspaces(doc_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            """SELECT w.id, w.name FROM workspaces w
               JOIN workspace_docs wd ON wd.workspace_id = w.id
               WHERE wd.doc_id = ?
               ORDER BY w.name""",
            (doc_id,),
        ).fetchall()


def get_workspace_documents(ws_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            """SELECT d.* FROM documents d
               JOIN workspace_docs wd ON wd.doc_id = d.id
               WHERE wd.workspace_id = ?
               ORDER BY d.created_at DESC""",
            (ws_id,),
        ).fetchall()
