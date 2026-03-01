"""REST API endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from core.api.models import ScanRequest, WaterfallRequest, LiveRequest, AudioToggleRequest
from core.api.runner import JobRunner


def create_routes(runner: JobRunner) -> APIRouter:
    router = APIRouter()

    @router.get("/api/status")
    async def get_status():
        return {"status": "online"}

    @router.post("/api/scan")
    async def start_scan(req: ScanRequest):
        job = runner.submit_scan(req.start_mhz, req.stop_mhz, req.duration, req.gain)
        return {"job_id": job.id, "status": job.status.value}

    @router.post("/api/waterfall")
    async def start_waterfall(req: WaterfallRequest):
        job = runner.submit_waterfall(req.start_mhz, req.stop_mhz, req.duration, req.gain)
        return {"job_id": job.id, "status": job.status.value}

    @router.post("/api/live/start")
    async def start_live(req: LiveRequest):
        runner.start_live(req.start_mhz, req.stop_mhz, req.gain,
                          req.audio_enabled, req.demod_mode)
        return {"status": "started", "start_mhz": req.start_mhz, "stop_mhz": req.stop_mhz,
                "audio_enabled": req.audio_enabled, "demod_mode": req.demod_mode}

    @router.post("/api/live/stop")
    async def stop_live():
        runner.stop_live()
        return {"status": "stopped"}

    @router.post("/api/live/audio")
    async def toggle_audio(req: AudioToggleRequest):
        if not runner.live_active:
            return JSONResponse({"error": "Live mode is not active"}, status_code=400)
        runner.toggle_audio(req.enabled, req.demod_mode)
        return {"audio_enabled": req.enabled, "demod_mode": req.demod_mode}

    return router
