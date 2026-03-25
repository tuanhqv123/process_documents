"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api import db as database
from api.routes.documents import router as docs_router, chunks_router, images_router
from api.routes.workspaces import router as ws_router

IMAGES_DIR = Path("data/images")

# Ensure data dirs exist at import time (needed before StaticFiles mount)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    yield


app = FastAPI(title="Knowledge Base API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static file serving for extracted images
app.mount("/static/images", StaticFiles(directory=str(IMAGES_DIR), html=False), name="images")

app.include_router(docs_router)
app.include_router(chunks_router)
app.include_router(images_router)
app.include_router(ws_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
