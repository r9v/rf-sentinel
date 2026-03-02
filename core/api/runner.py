"""Background job runner — executes SDR tasks in threads and streams logs."""

from __future__ import annotations

import time
import uuid
import logging
import traceback
from datetime import datetime, timezone
from typing import Callable, Optional
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor

from core.api.models import JobStatus
from core.api.live import LiveSession
import numpy as np

logger = logging.getLogger("rfsentinel.runner")

SCAN_WF_MAX_FREQ_BINS = 1024
SCAN_WF_MAX_TIME_BINS = 256


@dataclass
class Job:
    id: str
    type: str
    status: JobStatus
    params: dict
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None
    duration_s: Optional[float] = None


# Global callbacks — set by the server to push messages via WebSocket
_log_callback: Optional[Callable[[str, str], None]] = None
_audio_callback: Optional[Callable[[bytes], None]] = None
_job_status_callback: Optional[Callable[[dict], None]] = None


def set_log_callback(cb: Callable[[str, str], None]) -> None:
    global _log_callback
    _log_callback = cb


def set_audio_callback(cb: Callable[[bytes], None]) -> None:
    global _audio_callback
    _audio_callback = cb


def set_job_status_callback(cb: Callable[[dict], None]) -> None:
    global _job_status_callback
    _job_status_callback = cb


def _emit(job_id: str, msg: str) -> None:
    """Send a log line to the WebSocket callback."""
    if job_id != "__spectrum__":
        logger.info(f"[{job_id[:8]}] {msg}")
    if _log_callback:
        _log_callback(job_id, msg)


def _emit_audio(pcm_bytes: bytes) -> None:
    """Send binary PCM audio to the WebSocket callback."""
    if _audio_callback:
        _audio_callback(pcm_bytes)


def _emit_job_status(job: "Job") -> None:
    """Push job status update to the WebSocket callback."""
    if _job_status_callback:
        _job_status_callback({
            "id": job.id,
            "type": job.type,
            "status": job.status.value,
            "params": job.params,
            "error": job.error,
            "created_at": job.created_at.isoformat(),
            "duration_s": job.duration_s,
        })


class JobRunner:
    """Manages background SDR jobs."""

    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self._pool = ThreadPoolExecutor(max_workers=1)
        self.live = LiveSession(emit=_emit, emit_audio=_emit_audio)

    def _submit_job(self, job_type: str, params: dict, run_fn: Callable) -> Job:
        if self.live.active:
            self.live.stop()
        job_id = uuid.uuid4().hex[:12]
        job = Job(id=job_id, type=job_type, status=JobStatus.PENDING, params=params)
        self.jobs[job_id] = job
        _emit_job_status(job)
        self._pool.submit(run_fn, job)
        return job

    def submit_scan(self, start_mhz: float, stop_mhz: float,
                    duration: float, gain: float) -> Job:
        return self._submit_job("scan", {
            "start_mhz": start_mhz, "stop_mhz": stop_mhz,
            "duration": duration, "gain": gain,
        }, self._run_scan)

    # ── Shared helpers ──────────────────────────────────

    def _capture_segments(self, job: Job, label: str, compute_fn, trim_fn):
        """Capture I/Q across planned chunks, returning processed segments."""
        from core.dsp import plan_chunks, SAMPLE_RATE
        from core.sdr import SDRDevice, CaptureConfig

        p = job.params
        centers = plan_chunks(p["start_mhz"] * 1e6, p["stop_mhz"] * 1e6)
        num_chunks = len(centers)

        _emit(job.id, f"{label}: {p['start_mhz']:.1f} – {p['stop_mhz']:.1f} MHz "
              f"({num_chunks} chunk{'s' if num_chunks > 1 else ''})")

        segments = []
        with SDRDevice() as sdr:
            for i, fc in enumerate(centers):
                _emit(job.id, f"  [{i+1}/{num_chunks}] Capturing {fc/1e6:.1f} MHz...")
                config = CaptureConfig(
                    center_freq=fc, sample_rate=SAMPLE_RATE,
                    duration=p["duration"], gain=p["gain"],
                )
                capture = sdr.capture(config)
                data = compute_fn(capture)
                if num_chunks > 1:
                    data = trim_fn(data)
                segments.append(data)

        return segments, num_chunks

    @staticmethod
    def _log_peaks(job_id: str, peaks) -> None:
        """Emit peak detection results to the log stream."""
        if peaks:
            _emit(job_id, f"  Found {len(peaks)} signal{'s' if len(peaks) != 1 else ''}")
            for pk in peaks[:10]:
                _emit(job_id, f"    {pk.freq_mhz:.3f} MHz  {pk.power_db:+.1f} dB  (BW ~{pk.bandwidth_khz:.0f} kHz)")
            if len(peaks) > 10:
                _emit(job_id, f"    ... and {len(peaks) - 10} more")
        else:
            _emit(job_id, "  No signals above noise floor")

    def _finalize_job(self, job: Job, t0: float, peaks: list[dict]) -> None:
        job.status = JobStatus.COMPLETE
        job.duration_s = round(time.time() - t0, 2)
        job.params["peaks"] = peaks
        _emit_job_status(job)

    # ── Scan (stitched) ─────────────────────────────────

    def _run_scan(self, job: Job) -> None:
        job.status = JobStatus.RUNNING
        _emit_job_status(job)
        t0 = time.time()

        try:
            from core.dsp import compute_waterfall, trim_waterfall, stitch_waterfalls, find_peaks
            from core.dsp.classify import classify_peaks

            segments, num_chunks = self._capture_segments(job, "Scan", compute_waterfall, trim_waterfall)
            if num_chunks > 1:
                _emit(job.id, "  Note: chunks captured sequentially, not simultaneously")

            _emit(job.id, "Stitching spectrum..." if num_chunks > 1 else "Processing...")
            result = stitch_waterfalls(segments)

            _emit(job.id, "Detecting signals...")
            raw_peaks = find_peaks(result.freqs_mhz, result.mean_psd_db)
            self._log_peaks(job.id, raw_peaks)
            peaks = classify_peaks(result.freqs_mhz, result.mean_psd_db, raw_peaks)

            # 1D spectrum: send at full res (uPlot handles 25k+ points fine)
            spec_freqs = np.round(result.freqs_mhz, 4).tolist()
            spec_power = np.round(result.mean_psd_db, 1).tolist()

            # 2D waterfall: decimate more aggressively
            wf_freq_step = max(1, len(result.freqs_mhz) // SCAN_WF_MAX_FREQ_BINS)
            time_step = max(1, result.power_db.shape[1] // SCAN_WF_MAX_TIME_BINS)
            power_ds = result.power_db[::wf_freq_step, ::time_step]
            wf_freqs = np.round(result.freqs_mhz[::wf_freq_step], 4).tolist()

            job.params["waterfall_data"] = {
                "freqs_mhz": wf_freqs,
                "power_db": np.round(power_ds.T, 1).tolist(),
                "duration_s": round(float(result.times[-1]), 2),
            }
            job.params["spectrum_data"] = {
                "freqs_mhz": spec_freqs,
                "power_db": spec_power,
            }

            self._finalize_job(job, t0, peaks)
            _emit(job.id, f"Scan complete ({job.duration_s}s)")

        except Exception as e:
            job.status = JobStatus.ERROR
            job.error = str(e)
            job.duration_s = round(time.time() - t0, 2)
            _emit_job_status(job)
            _emit(job.id, f"ERROR: {e}")
            logger.error(traceback.format_exc())
        finally:
            import gc; gc.collect()
