"""
main.py — FastAPI entry point for the Memora backend
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import settings
from routers import persons, interactions, recognition, stream, admin

app = FastAPI(
    title="Memora API",
    description="AI-powered assistive system for Alzheimer's patients",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────
app.include_router(persons.router,       prefix="/api/persons",      tags=["Persons"])
app.include_router(interactions.router,  prefix="/api/interactions",  tags=["Interactions"])
app.include_router(recognition.router,   prefix="/api/recognition",   tags=["Recognition"])
app.include_router(stream.router,        prefix="/ws",                tags=["WebSocket"])
app.include_router(admin.router,         prefix="/api/admin",         tags=["Admin"])


@app.on_event("startup")
async def startup_warmup():
    """Pre-load detection + recognition models so the first webcam frame is fast."""
    import asyncio
    import numpy as np
    from services.face_pipeline import detect_faces, get_embedding

    dummy = np.zeros((100, 100, 3), dtype=np.uint8)
    await asyncio.to_thread(detect_faces, dummy, enforce_detection=False)
    await asyncio.to_thread(get_embedding, dummy)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=True,
    )
