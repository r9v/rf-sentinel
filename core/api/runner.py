"""Background job runner — executes SDR tasks in threads and streams logs."""

from __future__ import annotations

import gc
import time
import uuid
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor

from core.api.models import JobStatus
from core.plotting import render_scan_plot, render_waterfall_plot

logger = logging.getLogger("rfsentinel.runner")

# Output directory for plots
PLOTS_DIR = Path(__file__).resolve().parent.parent.parent / "plots"
PLOTS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Job:
    id: str
    type: str
    status: JobStatus
    params: dict
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    result_path: Optional[Path] = None
    error: Optional[str] = None
    duration_s: Optional[float] = None


# Global callbacks — set by the server to push messages via WebSocket
_log_callback: Optional[Callable[[str, str], None]] = None
_audio_callback: Optional[Callable[[bytes], None]] = None


def set_log_callback(cb: Callable[[str, str], None]) -> None:
    global _log_callback
    _log_callback = cb


def set_audio_callback(cb: Callable[[bytes], None]) -> None:
    global _audio_callback
    _audio_callback = cb


def _emit(job_id: str, msg: str) -> None:
    """Send a log line to the WebSocket callback."""
    logger.info(f"[{job_id[:8]}] {msg}")
    if _log_callback:
        _log_callback(job_id, msg)


def _emit_audio(pcm_bytes: bytes) -> None:
    """Send binary PCM audio to the WebSocket callback."""
    if _audio_callback:
        _audio_callback(pcm_bytes)


class JobRunner:
    """Manages background SDR jobs."""

    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._live_active = False
        self._live_thread = None
        self._audio_enabled = False
        self._demod_mode = "fm"

    def submit_scan(self, start_mhz: float, stop_mhz: float,
                    duration: float, gain: float) -> Job:
        if self._live_active:
            self.stop_live()
        job_id = uuid.uuid4().hex[:12]
        job = Job(
            id=job_id,
            type="scan",
            status=JobStatus.PENDING,
            params={"start_mhz": start_mhz, "stop_mhz": stop_mhz,
                    "duration": duration, "gain": gain},
        )
        self.jobs[job_id] = job
        self._pool.submit(self._run_scan, job)
        return job

    def submit_waterfall(self, start_mhz: float, stop_mhz: float,
                         duration: float, gain: float) -> Job:
        if self._live_active:
            self.stop_live()
        job_id = uuid.uuid4().hex[:12]
        job = Job(
            id=job_id,
            type="waterfall",
            status=JobStatus.PENDING,
            params={"start_mhz": start_mhz, "stop_mhz": stop_mhz,
                    "duration": duration, "gain": gain},
        )
        self.jobs[job_id] = job
        self._pool.submit(self._run_waterfall, job)
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    def list_jobs(self, limit: int = 20) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)[:limit]

    # ── Scan (stitched) ─────────────────────────────────

    def _run_scan(self, job: Job) -> None:
        job.status = JobStatus.RUNNING
        t0 = time.time()
        p = job.params

        try:
            from core.dsp import plan_chunks, compute_psd, trim_spectrum, stitch_spectra, SAMPLE_RATE
            from core.sdr import SDRDevice, CaptureConfig

            start_hz = p["start_mhz"] * 1e6
            stop_hz = p["stop_mhz"] * 1e6
            centers = plan_chunks(start_hz, stop_hz)
            num_chunks = len(centers)

            _emit(job.id, f"Scan: {p['start_mhz']:.1f} – {p['stop_mhz']:.1f} MHz ({num_chunks} chunk{'s' if num_chunks > 1 else ''})")

            segments = []
            for i, fc in enumerate(centers):
                fc_mhz = fc / 1e6
                _emit(job.id, f"  [{i+1}/{num_chunks}] Capturing {fc_mhz:.1f} MHz...")

                config = CaptureConfig(
                    center_freq=fc, sample_rate=SAMPLE_RATE,
                    duration=p["duration"], gain=p["gain"],
                )
                with SDRDevice() as sdr:
                    capture = sdr.capture(config)
                data = compute_psd(capture)

                if num_chunks > 1:
                    data = trim_spectrum(data)
                segments.append(data)

            _emit(job.id, "Stitching spectrum..." if num_chunks > 1 else "Processing...")
            result = stitch_spectra(segments)

            _emit(job.id, "Detecting signals...")
            from core.dsp import find_peaks as detect_peaks
            peaks = detect_peaks(result.freqs_mhz, result.power_db)
            if peaks:
                _emit(job.id, f"  Found {len(peaks)} signal{'s' if len(peaks) != 1 else ''}")
                for pk in peaks[:10]:
                    _emit(job.id, f"    {pk.freq_mhz:.3f} MHz  {pk.power_db:+.1f} dB  (BW ~{pk.bandwidth_khz:.0f} kHz)")
                if len(peaks) > 10:
                    _emit(job.id, f"    ... and {len(peaks) - 10} more")
            else:
                _emit(job.id, "  No signals above noise floor")

            _emit(job.id, "Rendering plot...")
            plot_path = PLOTS_DIR / f"scan_{job.id}.png"
            render_scan_plot(result, p, plot_path, peaks)

            job.result_path = plot_path
            job.status = JobStatus.COMPLETE
            job.duration_s = round(time.time() - t0, 2)
            job.params["peaks"] = [
                {"freq_mhz": pk.freq_mhz, "power_db": pk.power_db,
                 "prominence_db": pk.prominence_db, "bandwidth_khz": pk.bandwidth_khz}
                for pk in peaks
            ]
            _emit(job.id, f"Scan complete ({job.duration_s}s)")

        except Exception as e:
            job.status = JobStatus.ERROR
            job.error = str(e)
            job.duration_s = round(time.time() - t0, 2)
            _emit(job.id, f"ERROR: {e}")
            logger.error(traceback.format_exc())
        finally:
            gc.collect()

    # ── Waterfall (stitched) ────────────────────────────

    def _run_waterfall(self, job: Job) -> None:
        job.status = JobStatus.RUNNING
        t0 = time.time()
        p = job.params

        try:
            from core.dsp import (
                plan_chunks, compute_waterfall, trim_waterfall,
                stitch_waterfalls, SAMPLE_RATE,
            )
            from core.sdr import SDRDevice, CaptureConfig

            start_hz = p["start_mhz"] * 1e6
            stop_hz = p["stop_mhz"] * 1e6
            centers = plan_chunks(start_hz, stop_hz)
            num_chunks = len(centers)

            _emit(job.id, f"Waterfall: {p['start_mhz']:.1f} – {p['stop_mhz']:.1f} MHz ({num_chunks} chunk{'s' if num_chunks > 1 else ''})")
            if num_chunks > 1:
                _emit(job.id, f"  Note: chunks captured sequentially, not simultaneously")

            segments = []
            for i, fc in enumerate(centers):
                fc_mhz = fc / 1e6
                _emit(job.id, f"  [{i+1}/{num_chunks}] Capturing {fc_mhz:.1f} MHz...")

                config = CaptureConfig(
                    center_freq=fc, sample_rate=SAMPLE_RATE,
                    duration=p["duration"], gain=p["gain"],
                )
                with SDRDevice() as sdr:
                    capture = sdr.capture(config)
                data = compute_waterfall(capture)

                if num_chunks > 1:
                    data = trim_waterfall(data)
                segments.append(data)

            _emit(job.id, "Stitching waterfall..." if num_chunks > 1 else "Processing...")
            result = stitch_waterfalls(segments)

            _emit(job.id, "Detecting signals...")
            from core.dsp import find_peaks as detect_peaks
            peaks = detect_peaks(result.freqs_mhz, result.mean_psd_db)
            if peaks:
                _emit(job.id, f"  Found {len(peaks)} signal{'s' if len(peaks) != 1 else ''}")
                for pk in peaks[:10]:
                    _emit(job.id, f"    {pk.freq_mhz:.3f} MHz  {pk.power_db:+.1f} dB  (BW ~{pk.bandwidth_khz:.0f} kHz)")
                if len(peaks) > 10:
                    _emit(job.id, f"    ... and {len(peaks) - 10} more")
            else:
                _emit(job.id, "  No signals above noise floor")

            _emit(job.id, "Rendering waterfall plot...")
            plot_path = PLOTS_DIR / f"waterfall_{job.id}.png"
            render_waterfall_plot(result, p, plot_path, peaks)

            job.result_path = plot_path
            job.status = JobStatus.COMPLETE
            job.duration_s = round(time.time() - t0, 2)
            job.params["peaks"] = [
                {"freq_mhz": pk.freq_mhz, "power_db": pk.power_db,
                 "prominence_db": pk.prominence_db, "bandwidth_khz": pk.bandwidth_khz}
                for pk in peaks
            ]
            _emit(job.id, f"Waterfall complete ({job.duration_s}s)")

        except Exception as e:
            job.status = JobStatus.ERROR
            job.error = str(e)
            job.duration_s = round(time.time() - t0, 2)
            _emit(job.id, f"ERROR: {e}")
            logger.error(traceback.format_exc())
        finally:
            gc.collect()

    # ── Live mode ────────────────────────────────────────

    def start_live(self, start_mhz: float, stop_mhz: float, gain: float,
                    audio_enabled: bool = False, demod_mode: str = "fm") -> None:
        """Start continuous spectrum capture with optional audio demod."""
        if self._live_active:
            self.stop_live()

        from core.dsp import SAMPLE_RATE
        MAX_BW = SAMPLE_RATE / 1e6

        bw = stop_mhz - start_mhz
        if bw > MAX_BW:
            stop_mhz = start_mhz + MAX_BW

        center_hz = (start_mhz + stop_mhz) / 2 * 1e6
        bw_hz = (stop_mhz - start_mhz) * 1e6
        sample_rate = min(max(bw_hz, 0.25e6), SAMPLE_RATE)

        self._audio_enabled = audio_enabled
        self._demod_mode = demod_mode
        logger.info("live start: audio=%s demod=%s sr=%.0f Hz",
                     audio_enabled, demod_mode, sample_rate)

        self._live_active = True
        import threading
        self._live_thread = threading.Thread(
            target=self._live_loop,
            args=(center_hz, sample_rate, gain, start_mhz, stop_mhz),
            daemon=True,
        )
        self._live_thread.start()
        audio_tag = f" [audio: {demod_mode.upper()}]" if audio_enabled else ""
        _emit("live", f"Live started: {start_mhz:.1f}–{stop_mhz:.1f} MHz{audio_tag}")

    def stop_live(self) -> None:
        """Stop continuous spectrum capture."""
        self._live_active = False
        self._audio_enabled = False
        if self._live_thread:
            self._live_thread.join(timeout=3)
            self._live_thread = None
        logger.info("live stopped")
        _emit("live", "Live stopped")

    def toggle_audio(self, enabled: bool, demod_mode: str = "fm") -> None:
        """Toggle audio demod on/off while live is running."""
        self._audio_enabled = enabled
        self._demod_mode = demod_mode
        state = f"ON ({demod_mode.upper()})" if enabled else "OFF"
        logger.info("audio toggled: %s", state)
        _emit("live", f"Audio {state}")

    @property
    def live_active(self) -> bool:
        return self._live_active

    @property
    def audio_enabled(self) -> bool:
        return self._audio_enabled

    def _process_live_frame(self, capture, sample_rate: float,
                            frame_count: int) -> None:
        """Process a single live frame: spectrum + optional audio demod.

        Runs in a worker thread so the next USB capture can overlap.
        """
        import json
        from core.dsp import compute_psd, find_peaks, demodulate, DemodMode

        DOWNSAMPLE_POINTS = 1024

        result = compute_psd(capture, nfft=2048)

        step = max(1, len(result.freqs_mhz) // DOWNSAMPLE_POINTS)
        freqs = result.freqs_mhz[::step]
        power = result.power_db[::step]

        peaks = find_peaks(result.freqs_mhz, result.power_db)

        payload = json.dumps({
            "type": "spectrum",
            "freqs_mhz": freqs.tolist(),
            "power_db": power.tolist(),
            "peaks": [
                {"freq_mhz": pk.freq_mhz, "power_db": pk.power_db,
                 "bandwidth_khz": pk.bandwidth_khz}
                for pk in peaks
            ],
        })

        if _log_callback:
            _log_callback("__spectrum__", payload)

        if self._audio_enabled:
            try:
                mode = DemodMode(self._demod_mode)
                pcm = demodulate(capture.samples, sample_rate, mode)
                _emit_audio(pcm.tobytes())
            except Exception as e:
                logger.warning("audio demod error frame %d: %s", frame_count, e)

    def _live_loop(self, center_hz: float, sample_rate: float,
                   gain: float, start_mhz: float, stop_mhz: float) -> None:
        """Continuous capture loop with pipelined processing.

        Pipeline: process frame N in a worker thread while capturing frame N+1.
        This overlaps the ~250ms USB capture with ~70ms of processing,
        so cycle time ≈ max(capture, process) ≈ 250ms instead of their sum.
        """
        import threading
        from core.sdr import SDRDevice, CaptureConfig

        CAPTURE_DURATION = 0.25

        logger.info("live loop starting: fc=%.3f MHz sr=%.0f Hz gain=%.0f dB",
                     center_hz / 1e6, sample_rate, gain)

        try:
            config = CaptureConfig(
                center_freq=center_hz,
                sample_rate=sample_rate,
                gain=gain,
                duration=CAPTURE_DURATION,
            )

            frame_count = 0
            process_thread: threading.Thread | None = None

            with SDRDevice() as sdr:
                logger.info("live loop: SDR device opened (pipelined)")
                while self._live_active:
                    capture = sdr.capture(config)

                    if process_thread is not None:
                        process_thread.join()

                    process_thread = threading.Thread(
                        target=self._process_live_frame,
                        args=(capture, sample_rate, frame_count),
                        daemon=True,
                    )
                    process_thread.start()
                    frame_count += 1

            # Wait for last processing thread before exiting
            if process_thread is not None:
                process_thread.join(timeout=2)

        except Exception as e:
            _emit("live", f"Live error: {e}")
            logger.error(traceback.format_exc())
        finally:
            self._live_active = False
            self._audio_enabled = False
            logger.info("live loop exited after %d frames", frame_count if 'frame_count' in dir() else 0)

