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
_audio_ws_clients: list[WebSocket] = []
_loop: Optional[asyncio.AbstractEventLoop] = None


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


async def _broadcast(clients: list[WebSocket], sender) -> None:
    """Send data to all clients in a list, removing dead ones."""
    dead = []
    for ws in clients:
        try:
            await sender(ws)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.remove(ws)


def log_callback(job_id: str, message: str) -> None:
    """Thread-safe callback for the job runner to push messages via WebSocket."""
    if not (_loop and _loop.is_running()):
        return
    if job_id == "__spectrum__":
        payload = message  # already serialized JSON
    else:
        payload = json.dumps({"type": "log", "job_id": job_id, "message": message})
    asyncio.run_coroutine_threadsafe(
        _broadcast(_ws_clients, lambda ws: ws.send_text(payload)), _loop,
    )


def job_status_callback(job_dict: dict) -> None:
    """Thread-safe callback to push job status updates via WebSocket."""
    if not (_loop and _loop.is_running()):
        return
    payload = json.dumps({"type": "job_update", "job": job_dict})
    asyncio.run_coroutine_threadsafe(
        _broadcast(_ws_clients, lambda ws: ws.send_text(payload)), _loop,
    )


def audio_callback(data: bytes) -> None:
    """Thread-safe callback to send binary audio PCM via WebSocket."""
    if not (_loop and _loop.is_running()):
        return
    if not _audio_ws_clients:
        return
    asyncio.run_coroutine_threadsafe(
        _broadcast(_audio_ws_clients, lambda ws: ws.send_bytes(data)), _loop,
    )


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


@router.websocket("/api/ws/audio")
async def audio_websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    _audio_ws_clients.append(ws)
    logger.info(f"Audio WS connected ({len(_audio_ws_clients)} audio clients)")
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        _audio_ws_clients.remove(ws)
        logger.info(f"Audio WS disconnected ({len(_audio_ws_clients)} audio clients)")
