"""RFSentinel Web UI — FastAPI app setup and entry point."""

from __future__ import annotations

import asyncio
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(levelname)-5s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.api import ws
from core.api.routes import create_routes
from core.api.runner import JobRunner, set_log_callback, set_audio_callback, set_job_status_callback

logger = logging.getLogger("rfsentinel.server")

# ── App setup ───────────────────────────────────────────

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

runner = JobRunner()

app.include_router(ws.router)
app.include_router(create_routes(runner))


@app.on_event("startup")
async def _startup() -> None:
    ws.set_loop(asyncio.get_running_loop())
    set_log_callback(ws.log_callback)
    set_audio_callback(ws.audio_callback)
    set_job_status_callback(ws.job_status_callback)
    logger.info("RFSentinel server started (audio support enabled)")


@app.on_event("shutdown")
async def _shutdown() -> None:
    runner.live.stop()
    runner._pool.shutdown(wait=False)
    logger.info("RFSentinel server stopped")


# ── Entry point ─────────────────────────────────────────

def run_server(host: str = "127.0.0.1", port: int = 8900) -> None:
    import uvicorn

    print(f"\n  ╔══════════════════════════════════════╗")
    print(f"  ║     RFSentinel — UI Server           ║")
    print(f"  ║     http://{host}:{port}            ║")
    print(f"  ╚══════════════════════════════════════╝\n")

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8900)
    args = parser.parse_args()
    run_server(port=args.port)
