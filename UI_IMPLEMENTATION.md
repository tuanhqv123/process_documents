# UI Implementation for HTML, LaTeX, Formulas, and Images

## ✅ Completed Features

### 1. **HTML Format**
- **Backend**: Tables are already in HTML format from RapidDoc markdown
- **Database**: Added `html` column to `chunks` table
- **Frontend**: Display HTML content in markdown

### 2. **LaTeX Formulas**
- **Backend**:
  - Enabled formula extraction in pipeline (`formula_enable=True`)
  - Added `formulas` table to database
  - Store LaTeX strings with formula type (display/inline)
  - Store bbox for formula positions
- **Frontend**:
  - Added `FormulasPanel` component
  - Added formulas tab to document view
  - Shows formulas with syntax highlighting
  - Shows page numbers and formula types

### 3. **Images**
- **Backend**:
  - Real image saving to `data/images/doc_{id}/`
  - Extracted from RapidDoc pdf_info
  - Store bbox, image type, nearby text
- **Frontend**:
  - Existing `ImagesPanel` component
  - Shows images with OCR text
  - Display extracted images

### 4. **Database Schema**

**Documents Table:**
```sql
CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    filename    TEXT NOT NULL,
    file_path   TEXT NOT NULL,
    file_size   INTEGER DEFAULT 0,
    page_count  INTEGER DEFAULT 0,
    image_count INTEGER DEFAULT 0,
    chunk_count INTEGER DEFAULT 0,
    formula_count INTEGER DEFAULT 0,  -- ← Added
    status      TEXT DEFAULT 'pending',
    error       TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
```

**Chunks Table:**
```sql
CREATE TABLE IF NOT EXISTS chunks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id        INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index   INTEGER NOT NULL,
    text          TEXT NOT NULL,
    page_start    INTEGER DEFAULT 0,
    page_end      INTEGER DEFAULT 0,
    section_path  TEXT DEFAULT '[]',
    element_types TEXT DEFAULT '[]',
    html          TEXT DEFAULT '',  -- ← Added HTML content
    is_edited     INTEGER DEFAULT 0
);
```

**Formulas Table:**
```sql
CREATE TABLE IF NOT EXISTS formulas (  -- ← New table
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id       INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_num     INTEGER DEFAULT 0,
    latex        TEXT NOT NULL,
    formula_type TEXT DEFAULT 'display',
    bbox         TEXT DEFAULT '[]',
    is_edited    INTEGER DEFAULT 0
);
```

**DocImages Table (Enhanced):**
```sql
CREATE TABLE IF NOT EXISTS doc_images (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id       INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_num     INTEGER DEFAULT 0,
    image_path   TEXT NOT NULL,
    image_type   TEXT DEFAULT 'generic',
    ocr_text     TEXT DEFAULT '',
    nearby_text  TEXT DEFAULT '',
    bbox         TEXT DEFAULT '[]',  -- ← Added bbox
    is_edited    INTEGER DEFAULT 0
);
```

### 5. **API Endpoints**

**Added:**
- `GET /api/documents/{doc_id}/formulas` - Get all formulas
- Updated: `GET /api/documents/{doc_id}` - Returns `formula_count`
- Updated: `POST /api/documents/upload` - Triggers formula extraction

### 6. **Frontend Components**

**New Component:**
- `FormulasPanel` - Displays LaTeX formulas with syntax highlighting

**Updated Components:**
- `document-view.tsx` - Added formulas tab, formula count, live polling
- `api/client.ts` - Added `api.documents.formulas()`
- `types/index.ts` - Added `Formula` interface

### 7. **Pipeline Improvements**

**New Features:**
- **Real Image Saving**: Images saved to `data/images/doc_{id}/`
- **Formula Extraction**: LaTeX formulas extracted from pdf_info
- **HTML Content**: Tables returned in HTML format
- **Progress Tracking**: Shows formulas count in real-time

**Data Flow:**
```
RapidDoc → result_to_middle_json → pdf_info (with formulas/images)
                                    ↓
                            extract_formulas/images
                                    ↓
                    Save to database (formulas/images tables)
                                    ↓
                    Frontend polls and displays
```

### 8. **UI Features**

**Tabs:**
- **Pages**: Markdown content (with HTML tables)
- **Images**: Extracted images with OCR text
- **Formulas**: LaTeX formulas with syntax highlighting

**Real-time Updates:**
- Progress bar shows processing status
- Live polling of chunks/images/formulas
- Badge shows total counts

**Display:**
- **Formulas**: Syntax highlighted in code blocks
- **Images**: Show with page number and OCR text
- **Tables**: Rendered as HTML from markdown

### 9. **Chart Support**

**Status**: Ready to implement
- Charts are typically images in PDFs
- Will be extracted as images automatically
- Can be added to display if needed

---

## 🚀 Ready to Test

**Backend:**
```bash
source .venv/bin/activate
uvicorn api.main:app --reload --port 8000
```

**Frontend:**
```bash
cd web
npm run dev
```

**Test:**
1. Upload a PDF with formulas/tables
2. Watch real-time progress
3. Check formulas tab for LaTeX
4. Check images tab for extracted images
5. Verify tables are in HTML format

---

## 📊 Expected Results

**Processing Logs:**
```
[RapidDoc] Processing entire document...
[RapidDoc] Converting to middle JSON format...
[RapidDoc] Converting to markdown...
[RapidDoc] Markdown generated: 17K chars
[Page 1/40] 0.5s | Formulas: 3 | Images: 5
[Page 2/40] 0.3s | Formulas: 2 | Images: 3
...
```

**UI Display:**
- Formulas shown with LaTeX syntax highlighting
- Images displayed with OCR text and page numbers
- Tables rendered as HTML
- Real-time progress updates
- Count badges showing total formulas/images/chunks
