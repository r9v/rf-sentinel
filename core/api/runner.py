"""Background job runner — executes SDR tasks in threads and streams logs."""

from __future__ import annotations

import gc
import time
import uuid
import logging
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor

from core.api.models import JobStatus
from core.dsp.types import DemodMode
from core.plotting import render_waterfall_plot

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
            "result_url": f"/api/plots/{job.result_path.name}" if job.result_path else None,
            "error": job.error,
            "created_at": job.created_at.isoformat(),
            "duration_s": job.duration_s,
        })


class JobRunner:
    """Manages background SDR jobs."""

    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._live_active = False
        self._live_thread = None
        self._live_sdr: "SDRDevice | None" = None
        self._live_config = None
        self._audio_enabled = False
        self._demod_mode = DemodMode.FM
        self._demod_state = None

    def _submit_job(self, job_type: str, params: dict, run_fn: Callable) -> Job:
        if self._live_active:
            self.stop_live()
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

    def submit_waterfall(self, start_mhz: float, stop_mhz: float,
                         duration: float, gain: float) -> Job:
        return self._submit_job("waterfall", {
            "start_mhz": start_mhz, "stop_mhz": stop_mhz,
            "duration": duration, "gain": gain,
        }, self._run_waterfall)

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

    @staticmethod
    def _serialize_peaks(peaks) -> list[dict]:
        return [
            {"freq_mhz": pk.freq_mhz, "power_db": pk.power_db,
             "prominence_db": pk.prominence_db, "bandwidth_khz": pk.bandwidth_khz}
            for pk in peaks
        ]

    def _finalize_job(self, job: Job, t0: float, plot_path: Optional[Path], peaks) -> None:
        job.result_path = plot_path
        job.status = JobStatus.COMPLETE
        job.duration_s = round(time.time() - t0, 2)
        job.params["peaks"] = self._serialize_peaks(peaks)
        _emit_job_status(job)

    # ── Scan (stitched) ─────────────────────────────────

    def _run_scan(self, job: Job) -> None:
        job.status = JobStatus.RUNNING
        _emit_job_status(job)
        t0 = time.time()
        p = job.params

        try:
            from core.dsp import compute_psd, trim_spectrum, stitch_spectra, find_peaks

            segments, num_chunks = self._capture_segments(job, "Scan", compute_psd, trim_spectrum)

            _emit(job.id, "Stitching spectrum..." if num_chunks > 1 else "Processing...")
            result = stitch_spectra(segments)

            _emit(job.id, "Detecting signals...")
            peaks = find_peaks(result.freqs_mhz, result.power_db)
            self._log_peaks(job.id, peaks)

            step = max(1, len(result.freqs_mhz) // 2048)
            job.params["spectrum_data"] = {
                "freqs_mhz": result.freqs_mhz[::step].tolist(),
                "power_db": result.power_db[::step].tolist(),
            }

            self._finalize_job(job, t0, None, peaks)
            _emit(job.id, f"Scan complete ({job.duration_s}s)")

        except Exception as e:
            job.status = JobStatus.ERROR
            job.error = str(e)
            job.duration_s = round(time.time() - t0, 2)
            _emit_job_status(job)
            _emit(job.id, f"ERROR: {e}")
            logger.error(traceback.format_exc())
        finally:
            gc.collect()

    # ── Waterfall (stitched) ────────────────────────────

    def _run_waterfall(self, job: Job) -> None:
        job.status = JobStatus.RUNNING
        _emit_job_status(job)
        t0 = time.time()
        p = job.params

        try:
            from core.dsp import compute_waterfall, trim_waterfall, stitch_waterfalls, find_peaks

            segments, num_chunks = self._capture_segments(job, "Waterfall", compute_waterfall, trim_waterfall)
            if num_chunks > 1:
                _emit(job.id, "  Note: chunks captured sequentially, not simultaneously")

            _emit(job.id, "Stitching waterfall..." if num_chunks > 1 else "Processing...")
            result = stitch_waterfalls(segments)

            _emit(job.id, "Detecting signals...")
            peaks = find_peaks(result.freqs_mhz, result.mean_psd_db)
            self._log_peaks(job.id, peaks)

            _emit(job.id, "Rendering waterfall plot...")
            plot_path = PLOTS_DIR / f"waterfall_{job.id}.png"
            render_waterfall_plot(result, p, plot_path, peaks)

            self._finalize_job(job, t0, plot_path, peaks)
            _emit(job.id, f"Waterfall complete ({job.duration_s}s)")

        except Exception as e:
            job.status = JobStatus.ERROR
            job.error = str(e)
            job.duration_s = round(time.time() - t0, 2)
            _emit_job_status(job)
            _emit(job.id, f"ERROR: {e}")
            logger.error(traceback.format_exc())
        finally:
            gc.collect()

    # ── Live mode ────────────────────────────────────────

    @staticmethod
    def _live_params(start_mhz: float, stop_mhz: float) -> tuple[float, float, float, float]:
        """Compute center_hz, sample_rate, clamped start/stop for live mode."""
        from core.dsp import SAMPLE_RATE
        MAX_BW = SAMPLE_RATE / 1e6
        if stop_mhz - start_mhz > MAX_BW:
            stop_mhz = start_mhz + MAX_BW
        center_hz = (start_mhz + stop_mhz) / 2 * 1e6
        bw_hz = (stop_mhz - start_mhz) * 1e6
        sample_rate = min(max(bw_hz, 0.25e6), SAMPLE_RATE)
        return center_hz, sample_rate, start_mhz, stop_mhz

    def start_live(self, start_mhz: float, stop_mhz: float, gain: float,
                    audio_enabled: bool = False, demod_mode: DemodMode = DemodMode.FM) -> None:
        """Start continuous spectrum capture with optional audio demod."""
        if self._live_active:
            self.stop_live()

        center_hz, sample_rate, start_mhz, stop_mhz = self._live_params(start_mhz, stop_mhz)

        self._audio_enabled = audio_enabled
        self._demod_mode = demod_mode
        self._demod_state = None
        self._live_active = True
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
        if self._live_sdr:
            self._live_sdr.stop_stream()
        if self._live_thread:
            self._live_thread.join(timeout=3)
            self._live_thread = None
        self._live_sdr = None
        self._live_config = None
        _emit("live", "Live stopped")

    def retune_live(self, start_mhz: float, stop_mhz: float, gain: float) -> None:
        """Retune the live stream in-place — no stream interruption.

        Sets center_freq and gain via USB control transfers (I2C) which
        don't conflict with the bulk sample transfers already running.
        """
        if not self._live_active or not self._live_sdr:
            return

        from core.sdr import CaptureConfig

        center_hz, sample_rate, start_mhz, stop_mhz = self._live_params(start_mhz, stop_mhz)

        if self._live_config and sample_rate != self._live_config.sample_rate:
            _emit("live", "Sample rate changed — restarting stream")
            self.stop_live()
            self.start_live(start_mhz, stop_mhz, gain, self._audio_enabled, self._demod_mode)
            return

        self._live_sdr.retune(center_hz, gain)
        self._live_config = CaptureConfig(
            center_freq=center_hz, sample_rate=sample_rate,
            gain=gain, duration=0,
        )
        self._demod_state = None
        logger.debug("retune: fc=%.3f MHz gain=%.0f dB", center_hz / 1e6, gain)

    def toggle_audio(self, enabled: bool, demod_mode: DemodMode = DemodMode.FM) -> None:
        """Toggle audio demod on/off while live is running."""
        self._audio_enabled = enabled
        self._demod_mode = demod_mode
        self._demod_state = None
        state = f"ON ({demod_mode.upper()})" if enabled else "OFF"
        _emit("live", f"Audio {state}")

    @property
    def live_active(self) -> bool:
        return self._live_active

    @property
    def audio_enabled(self) -> bool:
        return self._audio_enabled

    def _process_live_frame(self, capture, sample_rate: float,
                            frame_count: int, send_spectrum: bool) -> None:
        """Process a single live frame.

        Audio demod runs every frame (time-sensitive for smooth playback).
        Spectrum (PSD + peaks + JSON) only runs when send_spectrum is True
        to avoid wasting CPU and WS bandwidth on every small frame.
        """
        from core.dsp import demodulate

        if self._audio_enabled:
            try:
                mode = DemodMode(self._demod_mode)
                pcm, self._demod_state = demodulate(
                    capture.samples, sample_rate, mode, self._demod_state,
                )
                _emit_audio(pcm.tobytes())
            except Exception as e:
                logger.warning("audio demod error frame %d: %s", frame_count, e)

        if send_spectrum:
            self._send_spectrum(capture)

    def _send_spectrum(self, capture) -> None:
        """Compute and send spectrum data over WebSocket."""
        import json
        from core.dsp import compute_psd, find_peaks

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

    def _live_loop(self, center_hz: float, sample_rate: float,
                   gain: float, start_mhz: float, stop_mhz: float) -> None:
        """Continuous streaming loop using async USB reads.

        Uses rtlsdr_read_async for gapless sample delivery.
        Retune happens in-place via SDR property setters (USB control
        transfers) without interrupting the bulk sample stream.
        """
        from core.sdr import SDRDevice, CaptureConfig, CaptureResult

        SPECTRUM_EVERY = 5
        frame_count = 0

        try:
            with SDRDevice() as sdr:
                self._live_sdr = sdr
                self._live_config = CaptureConfig(
                    center_freq=center_hz, sample_rate=sample_rate,
                    gain=gain, duration=0,
                )
                sdr.configure(self._live_config)
                chunk_samples = int(sample_rate * 0.1)
                def on_chunk(iq):
                    nonlocal frame_count
                    if not self._live_active:
                        sdr.stop_stream()
                        return
                    cfg = self._live_config
                    capture = CaptureResult(
                        samples=iq, config=cfg,
                        actual_duration=len(iq) / cfg.sample_rate,
                        num_samples=len(iq),
                    )
                    send_spectrum = (frame_count % SPECTRUM_EVERY == 0)
                    self._process_live_frame(capture, cfg.sample_rate, frame_count, send_spectrum)
                    frame_count += 1

                sdr.start_stream(on_chunk, chunk_samples)

        except Exception as e:
            _emit("live", f"Live error: {e}")
            logger.error(traceback.format_exc())
        finally:
            self._live_active = False
            self._audio_enabled = False
            self._live_sdr = None
            self._live_config = None
            logger.debug("live loop exited after %d frames", frame_count)

