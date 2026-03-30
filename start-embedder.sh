#!/bin/bash
# Start the native MLX embedding service (macOS only)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$SCRIPT_DIR/embedder_venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$SCRIPT_DIR/embedder_venv"
    source "$SCRIPT_DIR/embedder_venv/bin/activate"
    pip install -r "$SCRIPT_DIR/embedder/requirements.txt"
else
    source "$SCRIPT_DIR/embedder_venv/bin/activate"
fi

echo "Starting MLX Embedding Service on port 8001..."
cd "$SCRIPT_DIR"
uvicorn embedder.main:app --host 0.0.0.0 --port 8001
