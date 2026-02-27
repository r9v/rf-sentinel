"""RFSentinel Web UI — FastAPI server with WebSocket log streaming."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core.api.models import (
    ScanRequest, WaterfallRequest, LiveRequest, JobInfo, JobStatus,
)
from core.api.runner import JobRunner, set_log_callback, PLOTS_DIR

logger = logging.getLogger("rfsentinel.server")

# ── App setup ───────────────────────────────────────────

DEMO_MODE = os.environ.get("RFSENTINEL_DEMO", "0") == "1"

app = FastAPI(
    title="RFSentinel",
    description="RF Spectrum Monitoring & Classification",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

runner = JobRunner(demo_mode=DEMO_MODE)

# ── WebSocket management ────────────────────────────────

_ws_clients: list[WebSocket] = []


async def _broadcast_log(job_id: str, message: str) -> None:
    payload = json.dumps({"type": "log", "job_id": job_id, "message": message})
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.remove(ws)


_loop: Optional[asyncio.AbstractEventLoop] = None


async def _broadcast_raw(payload: str) -> None:
    """Send a pre-serialized JSON payload to all WebSocket clients."""
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.remove(ws)


def _sync_log_callback(job_id: str, message: str) -> None:
    if _loop and _loop.is_running():
        if job_id == "__spectrum__":
            # message is already a JSON payload for live spectrum data
            asyncio.run_coroutine_threadsafe(_broadcast_raw(message), _loop)
        else:
            asyncio.run_coroutine_threadsafe(_broadcast_log(job_id, message), _loop)


set_log_callback(_sync_log_callback)


@app.on_event("startup")
async def _capture_loop() -> None:
    global _loop
    _loop = asyncio.get_running_loop()
    mode = "DEMO" if DEMO_MODE else "LIVE (SDR)"
    logger.info(f"RFSentinel server started — mode: {mode}")


# ── WebSocket endpoint ──────────────────────────────────

@app.websocket("/api/ws")
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


# ── REST endpoints ──────────────────────────────────────

@app.get("/api/status")
async def get_status():
    return {
        "status": "online",
        "demo_mode": DEMO_MODE,
        "connected_clients": len(_ws_clients),
    }


@app.post("/api/scan")
async def start_scan(req: ScanRequest):
    job = runner.submit_scan(req.start_mhz, req.stop_mhz, req.duration, req.gain)
    return {"job_id": job.id, "status": job.status.value}


@app.post("/api/waterfall")
async def start_waterfall(req: WaterfallRequest):
    job = runner.submit_waterfall(req.start_mhz, req.stop_mhz, req.duration, req.gain)
    return {"job_id": job.id, "status": job.status.value}


# ── Live endpoints ──────────────────────────────────────

@app.post("/api/live/start")
async def start_live(req: LiveRequest):
    runner.start_live(req.start_mhz, req.stop_mhz, req.gain)
    return {"status": "started", "start_mhz": req.start_mhz, "stop_mhz": req.stop_mhz}


@app.post("/api/live/stop")
async def stop_live():
    runner.stop_live()
    return {"status": "stopped"}


@app.get("/api/live/status")
async def live_status():
    return {"active": runner.live_active}


@app.get("/api/jobs")
async def list_jobs():
    jobs = runner.list_jobs()
    return [
        JobInfo(
            id=j.id,
            type=j.type,
            status=j.status,
            params=j.params,
            result_url=f"/api/plots/{j.result_path.name}" if j.result_path else None,
            error=j.error,
            created_at=j.created_at.isoformat(),
            duration_s=j.duration_s,
        ).model_dump()
        for j in jobs
    ]


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = runner.get_job(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    return JobInfo(
        id=job.id,
        type=job.type,
        status=job.status,
        params=job.params,
        result_url=f"/api/plots/{job.result_path.name}" if job.result_path else None,
        error=job.error,
        created_at=job.created_at.isoformat(),
        duration_s=job.duration_s,
    ).model_dump()


# Serve plot images
app.mount("/api/plots", StaticFiles(directory=str(PLOTS_DIR)), name="plots")


# ── Entry point ─────────────────────────────────────────

def run_server(host: str = "127.0.0.1", port: int = 8900, demo: bool = False) -> None:
    import uvicorn

    if demo:
        os.environ["RFSENTINEL_DEMO"] = "1"
        global DEMO_MODE
        DEMO_MODE = True
        runner.demo_mode = True

    print(f"\n  ╔══════════════════════════════════════╗")
    print(f"  ║     RFSentinel — UI Server           ║")
    print(f"  ║     http://{host}:{port}            ║")
    print(f"  ║     Mode: {'DEMO' if demo or DEMO_MODE else 'LIVE (SDR)':>10}             ║")
    print(f"  ╚══════════════════════════════════════╝\n")

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="Run with synthetic data (no SDR)")
    parser.add_argument("--port", type=int, default=8900)
    args = parser.parse_args()
    run_server(port=args.port, demo=args.demo)
