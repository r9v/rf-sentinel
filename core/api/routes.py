"""REST API endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from core.api.models import ScanRequest, LiveRequest, RetuneRequest, AudioToggleRequest, VfoRequest, RecordStartRequest
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

    @router.post("/api/live/start")
    async def start_live(req: LiveRequest):
        runner.live.start(req.start_mhz, req.stop_mhz, req.gain,
                          req.audio_enabled, req.demod_mode)
        return {"status": "started", "start_mhz": req.start_mhz, "stop_mhz": req.stop_mhz,
                "audio_enabled": req.audio_enabled, "demod_mode": req.demod_mode}

    @router.post("/api/live/stop")
    async def stop_live():
        runner.live.stop()
        return {"status": "stopped"}

    @router.post("/api/live/retune")
    async def retune_live(req: RetuneRequest):
        if not runner.live.active:
            return JSONResponse({"error": "Live mode is not active"}, status_code=400)
        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, runner.live.retune, req.start_mhz, req.stop_mhz, req.gain)
        return {"status": "retuned", "start_mhz": req.start_mhz, "stop_mhz": req.stop_mhz}

    @router.post("/api/live/audio")
    async def toggle_audio(req: AudioToggleRequest):
        if not runner.live.active:
            return JSONResponse({"error": "Live mode is not active"}, status_code=400)
        runner.live.toggle_audio(req.enabled, req.demod_mode)
        return {"audio_enabled": req.enabled, "demod_mode": req.demod_mode}

    @router.post("/api/live/vfo")
    async def set_vfo(req: VfoRequest):
        if not runner.live.active:
            return JSONResponse({"error": "Live mode is not active"}, status_code=400)
        runner.live.set_vfo(req.freq_mhz)
        return {"vfo_freq_mhz": req.freq_mhz}

    @router.post("/api/live/record/start")
    async def start_recording(req: RecordStartRequest):
        if not runner.live.active:
            return JSONResponse({"error": "Live mode is not active"}, status_code=400)
        try:
            result = runner.live.start_recording(req.mode, req.bandwidth_khz)
            return result
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @router.post("/api/live/record/stop")
    async def stop_recording():
        if not runner.live.active:
            return JSONResponse({"error": "Live mode is not active"}, status_code=400)
        result = runner.live.stop_recording()
        if not result:
            return JSONResponse({"error": "Not recording"}, status_code=400)
        return result

    @router.get("/api/recordings")
    async def get_recordings(limit: int = 50, offset: int = 0):
        from core.api.db import list_recordings
        return list_recordings(limit, offset)

    @router.delete("/api/recordings/{rec_id}")
    async def delete_recording(rec_id: str):
        from core.api.db import delete_recording as db_delete_rec
        if db_delete_rec(rec_id):
            return {"status": "deleted"}
        return JSONResponse({"error": "Recording not found"}, status_code=404)

    @router.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str):
        if runner.cancel_job(job_id):
            return {"status": "cancelled"}
        return JSONResponse({"error": "Job not found or not cancellable"}, status_code=404)

    @router.get("/api/scans")
    async def get_scan_history(limit: int = 50, offset: int = 0):
        from core.api.db import list_scans
        return list_scans(limit, offset)

    @router.get("/api/scans/{scan_id}")
    async def get_scan_detail(scan_id: str):
        from core.api.db import get_scan
        result = get_scan(scan_id)
        if not result:
            return JSONResponse({"error": "Scan not found"}, status_code=404)
        return result

    @router.delete("/api/scans/{scan_id}")
    async def delete_scan(scan_id: str):
        from core.api.db import delete_scan as db_delete
        runner.jobs.pop(scan_id, None)
        if db_delete(scan_id):
            return {"status": "deleted"}
        return JSONResponse({"error": "Scan not found"}, status_code=404)

    return router
