"""WebSocket client management and log streaming."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("rfsentinel.ws")

router = APIRouter()

_ws_clients: list[WebSocket] = []
_loop: Optional[asyncio.AbstractEventLoop] = None


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def client_count() -> int:
    return len(_ws_clients)


async def _broadcast(payload: str) -> None:
    """Send a text payload to all connected WebSocket clients."""
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.remove(ws)


async def _broadcast_bytes(data: bytes) -> None:
    """Send binary data to all connected WebSocket clients."""
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_bytes(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.remove(ws)
    if dead:
        logger.debug("audio broadcast: dropped %d dead clients", len(dead))


def log_callback(job_id: str, message: str) -> None:
    """Thread-safe callback for the job runner to push messages via WebSocket."""
    if not (_loop and _loop.is_running()):
        return
    if job_id == "__spectrum__":
        payload = message  # already serialized JSON
    else:
        payload = json.dumps({"type": "log", "job_id": job_id, "message": message})
    asyncio.run_coroutine_threadsafe(_broadcast(payload), _loop)


def audio_callback(data: bytes) -> None:
    """Thread-safe callback to send binary audio PCM via WebSocket."""
    if not (_loop and _loop.is_running()):
        return
    if not _ws_clients:
        return
    asyncio.run_coroutine_threadsafe(_broadcast_bytes(data), _loop)


@router.websocket("/api/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    _ws_clients.append(ws)
    logger.info(f"WebSocket connected ({len(_ws_clients)} clients)")
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        _ws_clients.remove(ws)
        logger.info(f"WebSocket disconnected ({len(_ws_clients)} clients)")
