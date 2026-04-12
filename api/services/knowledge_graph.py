"""Knowledge graph builder from OCR layout output.

Tree structure:
    Document (root, rank=0)  ← filename
    └── Page N  (rank=1)     ← one node per page
        └── Section  (rank=2) ← Title or Section-header
            ├── Text  (rank=3, leaf)
            ├── Table (rank=3, leaf)
            └── Picture (rank=3, leaf)

Cross-page rule:
    If page N+1 starts without a new section header, its content
    is still placed under the last active section from page N.
    A new section header on any page resets the active section.
"""

import logging
import re
from typing import Optional
from sqlalchemy.orm import Session

from api.db import Document, DocumentNode

logger = logging.getLogger(__name__)

SKIP_CATEGORIES = {"Page-header", "Page-footer"}
SECTION_CATEGORIES = {"Title", "Section-header"}


def _strip_html(text: str) -> str:
    """Strip HTML tags — used to clean table text for embedding."""
    return re.sub(r"<[^>]+>", " ", text).strip()


def _table_to_plain(html: str) -> str:
    """Convert HTML table to pipe-delimited plain text preserving row structure.

    E.g.: <tr><td>SVM</td><td>95%</td></tr>  →  SVM | 95%
    """
    # Replace closing tr with newline marker
    text = re.sub(r"</tr\s*>", "\n", html, flags=re.IGNORECASE)
    # Replace td/th tags with pipe separator
    text = re.sub(r"<t[dh][^>]*>", " | ", text, flags=re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Clean up whitespace and leading pipes
    lines = []
    for line in text.splitlines():
        line = re.sub(r"\s*\|\s*", " | ", line).strip().strip("|").strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def build_graph(doc_id: int, ocr_pages: list[dict], db: Session) -> DocumentNode:
    """Build the knowledge graph for a document from OCR page data.

    Deletes any existing nodes for this document, then inserts a fresh tree.
    Returns the root document node.
    """
    db.query(DocumentNode).filter(DocumentNode.doc_id == doc_id).delete()
    db.commit()

    doc = db.query(Document).filter(Document.id == doc_id).first()
    doc_title = doc.filename if doc else f"Document {doc_id}"

    # ── Root: Document node ────────────────────────────────────────────────────
    root = DocumentNode(
        doc_id=doc_id,
        parent_id=None,
        category="Document",
        text=doc_title,
        page_num=0,
        position=0,
        node_rank=0,
        depth=0,
    )
    db.add(root)
    db.flush()
    root.path = str(root.id)
    db.flush()

    position = 0

    # Track current section across pages (cross-page carry-over)
    current_section_id: Optional[int] = None
    current_section_path: Optional[str] = None

    for page_data in ocr_pages:
        page_num = page_data.get("page", 0)
        layout_json = page_data.get("layout_json", [])

        # ── Page node ─────────────────────────────────────────────────────────
        position += 1
        page_node = DocumentNode(
            doc_id=doc_id,
            parent_id=root.id,
            category="Page",
            text=f"Page {page_num}",
            page_num=page_num,
            position=position,
            node_rank=1,
            depth=1,
        )
        db.add(page_node)
        db.flush()
        page_node.path = f"{root.path}.{page_node.id}"
        db.flush()

        # Use OCR model's reading order directly — do NOT re-sort by y1
        for el in layout_json:
            category = el.get("category", "Text")
            text = (el.get("text") or "").strip()
            bbox = el.get("bbox")

            if category in SKIP_CATEGORIES:
                continue

            position += 1

            if category in SECTION_CATEGORIES:
                # ── New section: child of the current page ─────────────────
                sec = DocumentNode(
                    doc_id=doc_id,
                    parent_id=page_node.id,
                    category=category,
                    text=text,
                    page_num=page_num,
                    bbox=bbox,
                    position=position,
                    node_rank=2,
                    depth=2,
                )
                db.add(sec)
                db.flush()
                sec.path = f"{page_node.path}.{sec.id}"
                db.flush()

                current_section_id = sec.id
                current_section_path = sec.path

            else:
                # ── Leaf content ───────────────────────────────────────────
                # Goes under current section if one is active, otherwise page
                if current_section_id:
                    parent_id = current_section_id
                    parent_path = current_section_path
                    depth = 3
                else:
                    parent_id = page_node.id
                    parent_path = page_node.path
                    depth = 2

                leaf = DocumentNode(
                    doc_id=doc_id,
                    parent_id=parent_id,
                    category=category,
                    text=text,
                    page_num=page_num,
                    bbox=bbox,
                    position=position,
                    node_rank=3,
                    depth=depth,
                )
                # Populate plain_text for embedding
                if category == "Table":
                    leaf.plain_text = _table_to_plain(text)
                else:
                    leaf.plain_text = text  # Text, Picture, Figure — already plain
                db.add(leaf)
                db.flush()
                leaf.path = f"{parent_path}.{leaf.id}"
                db.flush()

    db.commit()
    return root


# ── Query helpers ──────────────────────────────────────────────────────────────

def get_tree(doc_id: int, db: Session) -> Optional[dict]:
    """Return the full document tree as a nested dict for API response."""
    nodes = (
        db.query(DocumentNode)
        .filter(DocumentNode.doc_id == doc_id)
        .order_by(DocumentNode.position)
        .all()
    )
    if not nodes:
        return None

    children_map: dict[int, list[DocumentNode]] = {n.id: [] for n in nodes}
    root_node = None

    for n in nodes:
        if n.parent_id is None:
            root_node = n
        elif n.parent_id in children_map:
            children_map[n.parent_id].append(n)

    if not root_node:
        return None

    def to_dict(node: DocumentNode) -> dict:
        return {
            "id": node.id,
            "category": node.category,
            "text": node.text[:200] if node.text else "",
            "page_num": node.page_num,
            "depth": node.depth,
            "rank": node.node_rank,
            "path": node.path,
            "bbox": node.bbox,
            "children": [
                to_dict(c)
                for c in sorted(children_map[node.id], key=lambda x: x.position)
            ],
        }

    return to_dict(root_node)


def get_ancestors(node_id: int, db: Session) -> list[dict]:
    """Return all ancestors of a node ordered from root to parent."""
    node = db.query(DocumentNode).filter(DocumentNode.id == node_id).first()
    if not node or not node.path:
        return []

    from sqlalchemy import text
    result = db.execute(
        text("""
            SELECT id, category, text, depth, path, page_num
            FROM document_nodes
            WHERE CAST(path AS ltree) @> CAST(:node_path AS ltree)
              AND path != :node_path
            ORDER BY depth ASC
        """),
        {"node_path": node.path},
    )
    return [
        {"id": r.id, "category": r.category, "text": r.text, "depth": r.depth}
        for r in result.fetchall()
    ]


def get_context_for_node(node_id: int, db: Session) -> str:
    """Build embedding context: 'filename > section heading > leaf text'.

    - Document name    → disambiguation across multiple docs in a workspace
    - Section heading  → semantic context (what topic this belongs to)
    - Leaf text        → the actual content (cleaned of HTML/LaTeX noise)

    Tables: HTML stripped to plain text for the embedding.
    Formulas: replaced with [formula] — LaTeX is opaque to embedding models.
    """
    node = db.query(DocumentNode).filter(DocumentNode.id == node_id).first()
    if not node:
        return ""

    ancestors = get_ancestors(node_id, db)

    doc_name = next(
        (a["text"] for a in ancestors if a["category"] == "Document"), ""
    )
    section_text = next(
        (a["text"] for a in ancestors if a["category"] in SECTION_CATEGORIES), ""
    )

    # Clean leaf text for embedding
    if node.category == "Formula":
        leaf_text = "[formula]"
    else:
        leaf_text = node.plain_text or _strip_html(node.text or "")

    parts = [p for p in [doc_name, section_text, leaf_text] if p]
    return " > ".join(parts)


def embed_leaf_nodes(doc_id: int, db: Session) -> int:
    """Embed all leaf nodes (rank=3) using the embedding service.
    Returns the number of nodes embedded.
    """
    from api.embedding_client import embedding_client

    leaf_nodes = (
        db.query(DocumentNode)
        .filter(
            DocumentNode.doc_id == doc_id,
            DocumentNode.node_rank == 3,
            DocumentNode.text != "",
        )
        .all()
    )
    if not leaf_nodes:
        return 0

    texts = [get_context_for_node(n.id, db) for n in leaf_nodes]

    try:
        embeddings = embedding_client.embed_texts(texts)
        for node, emb in zip(leaf_nodes, embeddings):
            node.embedding = emb
        db.commit()
        return len(leaf_nodes)
    except Exception as e:
        logger.warning("Embedding leaf nodes failed: %s", e)
        return 0
