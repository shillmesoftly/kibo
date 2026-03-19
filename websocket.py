"""
websocket.py
Manages all connected WebSocket clients.
Registers itself as the broadcast target on KiboEngine so every
HP change is pushed to every open browser tab instantly.
"""

import asyncio
import json
import logging
from fastapi import WebSocket, WebSocketDisconnect

from state import kibo_engine

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)
        logger.info(f"Client connected. Total: {len(self.active)}")
        # Send current state immediately on connect
        await self._send(ws, kibo_engine.get_state())

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active:
            self.active.remove(ws)
        logger.info(f"Client disconnected. Total: {len(self.active)}")

    async def broadcast(self, data: dict) -> None:
        """Push state update to all connected clients."""
        if not self.active:
            return
        payload = json.dumps({"type": "state_update", "data": data})
        dead: list[WebSocket] = []
        for ws in self.active:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def _send(self, ws: WebSocket, data: dict) -> None:
        try:
            await ws.send_text(json.dumps({"type": "state_update", "data": data}))
        except Exception as e:
            logger.warning(f"Failed to send to client: {e}")


manager = ConnectionManager()

# Wire engine → websocket broadcast
kibo_engine.set_broadcast(manager.broadcast)


async def websocket_endpoint(ws: WebSocket) -> None:
    """
    Mount this on your FastAPI router:
        @app.websocket("/ws")
        async def ws_route(ws: WebSocket):
            await websocket_endpoint(ws)
    """
    await manager.connect(ws)
    try:
        while True:
            # Keep connection alive; client messages are optional
            # (client can send {"type": "ping"} to keep alive)
            raw = await ws.receive_text()
            msg = json.loads(raw)

            if msg.get("type") == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))

            elif msg.get("type") == "feed":
                # Direct feed from UI (wallet tx already confirmed client-side)
                # Production: only trust feeds from solana_watcher.py
                tokens = int(msg.get("tokens", 100))
                state = await kibo_engine.handle_feed(tokens)
                # broadcast() already called inside handle_feed

            elif msg.get("type") == "reset":
                await kibo_engine.reset()

    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(ws)
