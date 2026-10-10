"""DALIL API application: FastAPI + static SPA hosting."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .api.routes import get_llm, load_queue, router
from .core.riskmodel import load_bundle


@asynccontextmanager
async def lifespan(app: FastAPI):
    # warm the model so the first analysed case is fast
    load_bundle()
    load_queue()
    get_llm().health(timeout=2.0)
    yield


app = FastAPI(title="DALIL — AML investigation copilot", version="1.0.0", lifespan=lifespan)
app.include_router(router)


@app.get("/api/version")
def version() -> dict:
    return {"name": "dalil", "version": "1.0.0"}


# --- static SPA (frontend/dist) ------------------------------------------
if config.STATIC_DIR.exists():
    assets = config.STATIC_DIR / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"error": "unknown endpoint"}, status_code=404)
        candidate = config.STATIC_DIR / full_path
        if full_path and candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        index = config.STATIC_DIR / "index.html"
        if index.exists():
            return FileResponse(index)
        return JSONResponse({"error": "frontend not built"}, status_code=404)
