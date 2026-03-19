"""
main.py
FastAPI entry point for the $KIBO backend.

Endpoints:
  GET  /           → health check
  GET  /state      → current Kibo state (JSON)
  POST /feed       → manual feed trigger (dev/testing only)
  POST /reset      → start new season
  WS   /ws         → real-time HP updates
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from state import kibo_engine
from websocket import websocket_endpoint
from solana_watcher import solana_watcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://kibo.vercel.app")


# ── LIFESPAN ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting $KIBO backend...")
    await kibo_engine.start()
    await solana_watcher.start()
    yield
    logger.info("Shutting down $KIBO backend")


# ── APP ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="$KIBO Backend",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:3000", "http://localhost:5500"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── ROUTES ────────────────────────────────────────────────────────────────────
@app.get("/")
async def health():
    return {"status": "alive", "service": "$KIBO backend"}


@app.get("/state")
async def get_state():
    """Returns current Kibo HP state. Frontend polls this on initial load."""
    return JSONResponse(kibo_engine.get_state())


@app.post("/feed")
async def feed(tokens: int = 100):
    """
    Dev/webhook endpoint to trigger a feed manually.
    In production, feeds come exclusively from solana_watcher detecting
    real on-chain burns — this endpoint should be disabled or auth-gated.
    """
    state = await kibo_engine.handle_feed(tokens)
    return JSONResponse(state)


@app.post("/reset")
async def reset():
    """Start a new season. Should be admin-only in production."""
    state = await kibo_engine.reset()
    return JSONResponse(state)


@app.websocket("/ws")
async def ws_route(ws: WebSocket):
    await websocket_endpoint(ws)
