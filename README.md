# PDF Processor - RapidDoc Integration

Fast document processing with RapidDoc (OCR, layout, tables, formulas).

## 🚀 Quick Start

### Prerequisites
- Python 3.10.18 (`python3.10`)
- Node.js 18+ (for frontend)
- npm or yarn

### Installation

```bash
# 1. Create virtual environment with Python 3.10
python3.10 -m venv .venv

# 2. Activate virtual environment
source .venv/bin/activate

# 3. Install Python dependencies
python -m pip install -e . -i https://mirrors.aliyun.com/pypi/simple

# 4. Install frontend dependencies
cd web
npm install
cd ..
```

**⚠️ Important:** Always use `python3.10` to create the venv! The project requires Python 3.10.18, not 3.13/3.14.

## 🏃 Running the Application

### Option 1: Run Backend & Frontend Separately (Recommended)

**Terminal 1 - Backend:**
```bash
source .venv/bin/activate
uvicorn api.main:app --reload --port 8000
```

**Terminal 2 - Frontend:**
```bash
cd web
npm run dev
```

### Option 2: Run Both in One Terminal

```bash
# Backend (in background)
source .venv/bin/activate && uvicorn api.main:app --reload --port 8000 &

# Frontend (wait 2 seconds)
sleep 2 && cd web && npm run dev
```

## 🌐 Accessing the Application

- **Frontend:** http://localhost:5173
- **Backend API:** http://localhost:8000
- **API Docs:** http://localhost:8000/docs
- **Health Check:** http://localhost:8000/api/health

## 📦 Project Structure

```
process_documents/
├── api/                 # Backend (FastAPI)
│   ├── pipeline.py       # RapidDoc processing
│   ├── processor.py      # Background processing
│   ├── main.py          # FastAPI app
│   ├── db.py            # Database
│   └── routes/          # API routes
├── web/                 # Frontend (React + Vite)
│   ├── src/
│   ├── package.json
│   └── vite.config.ts
├── pyproject.toml        # Python dependencies
└── run.py              # Standalone CLI
```

## 🔧 Development

### Backend
```bash
# Run with auto-reload
source .venv/bin/activate
uvicorn api.main:app --reload --port 8000

# Run specific module
python run.py "path/to/document.pdf"
```

### Frontend
```bash
cd web

# Development server
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

## 🛠️ Troubleshooting

### Backend Issues

**Port 8000 in use:**
```bash
lsof -i :8000
kill -9 $(lsof -t -i:8000)
```

**UnicodeEncodeError / Surrogate Pairs:**
This is automatically handled now. If you see errors, the text will be cleaned and stored with replacements.

**Import errors:**
```bash
# Recreate venv with correct Python version
rm -rf .venv
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install -e . -i https://mirrors.aliyun.com/pypi/simple
```

### Frontend Issues

**Clear cache:**
```bash
cd web
rm -rf node_modules package-lock.json
npm install
```

**Port 5173 in use:**
```bash
lsof -i :5173
kill -9 $(lsof -t -i:5173)
```

## 📊 Features

- ✅ **OCR:** RapidOCR with PP-OCRv5
- ✅ **Layout:** PP-DocLayoutV2 (20 categories)
- ✅ **Tables:** RapidTable (HTML format)
- ✅ **Formulas:** PP-FormulaNet_plus-M (LaTeX)
- ✅ **Reading Order:** Natural reading order
- ✅ **Page-by-page:** Streaming processing
- ✅ **Real-time:** Live progress updates
- ✅ **Unicode Support:** Handles emojis, surrogate pairs, special characters

## ⚠️ Known Warnings (Safe to Ignore)

- `RuntimeWarning: invalid value encountered in scalar divide` - Numpy warning in table recognition, not an error
- `OpenVINO 可用性检查出错: No module named 'openvino'` - Falls back to ONNXRuntime, not an error

## 📝 License

Apache 2.0
