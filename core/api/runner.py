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

import numpy as np
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt

from core.api.models import JobStatus

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


# Global log callback — set by the server to push messages via WebSocket
_log_callback: Optional[Callable[[str, str], None]] = None


def set_log_callback(cb: Callable[[str, str], None]) -> None:
    global _log_callback
    _log_callback = cb


def _emit(job_id: str, msg: str) -> None:
    """Send a log line to the WebSocket callback."""
    logger.info(f"[{job_id[:8]}] {msg}")
    if _log_callback:
        _log_callback(job_id, msg)


class JobRunner:
    """Manages background SDR jobs."""

    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._live_active = False
        self._live_thread = None

    def submit_scan(self, start_mhz: float, stop_mhz: float,
                    duration: float, gain: float) -> Job:
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
            self._render_scan_plot(result, p, plot_path, peaks)

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

    def _render_scan_plot(self, data, params: dict, path: Path, peaks=None) -> None:
        fig, ax = plt.subplots(figsize=(14, 4))
        fig.patch.set_facecolor("#0a0e1a")
        ax.set_facecolor("#0f1525")

        freqs = data.freqs_mhz if hasattr(data, 'freqs_mhz') else data["freqs_mhz"]
        power = data.power_db if hasattr(data, 'power_db') else data["power_db"]

        ax.plot(freqs, power, linewidth=0.5, color="#00d4ff")
        ax.fill_between(freqs, np.min(power), power, alpha=0.12, color="#00d4ff")

        if peaks:
            for pk in peaks:
                ax.plot(pk.freq_mhz, pk.power_db, 'v', color='#ff6b35',
                        markersize=6, markeredgecolor='#ff6b35', markeredgewidth=0.5)
                ax.annotate(
                    f"{pk.freq_mhz:.3f}",
                    xy=(pk.freq_mhz, pk.power_db),
                    xytext=(0, 8), textcoords='offset points',
                    fontsize=6, color='#ff6b35', ha='center',
                    fontweight='bold',
                )

        ax.set_xlabel("Frequency [MHz]", color="#a0a0a0")
        ax.set_ylabel("Power [dB]", color="#a0a0a0")

        n_peaks = len(peaks) if peaks else 0
        title = f"PSD — {params['start_mhz']:.1f}–{params['stop_mhz']:.1f} MHz"
        if n_peaks:
            title += f"  ({n_peaks} signal{'s' if n_peaks != 1 else ''})"
        ax.set_title(title, color="#e0e0e0", fontsize=13, fontweight="bold")

        ax.tick_params(colors="#808080")
        ax.grid(True, alpha=0.15, color="#ffffff")
        ax.set_xlim(freqs[0], freqs[-1])
        for spine in ax.spines.values():
            spine.set_color("#2a2a3a")

        plt.tight_layout()
        fig.savefig(path, dpi=150, facecolor=fig.get_facecolor())
        plt.close(fig)

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
            self._render_waterfall_plot(result, p, plot_path, peaks)

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

    def start_live(self, start_mhz: float, stop_mhz: float, gain: float) -> None:
        """Start continuous spectrum capture."""
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

        self._live_active = True
        import threading
        self._live_thread = threading.Thread(
            target=self._live_loop,
            args=(center_hz, sample_rate, gain, start_mhz, stop_mhz),
            daemon=True,
        )
        self._live_thread.start()
        _emit("live", f"Live started: {start_mhz:.1f}–{stop_mhz:.1f} MHz")

    def stop_live(self) -> None:
        """Stop continuous spectrum capture."""
        self._live_active = False
        if self._live_thread:
            self._live_thread.join(timeout=3)
            self._live_thread = None
        _emit("live", "Live stopped")

    @property
    def live_active(self) -> bool:
        return self._live_active

    def _live_loop(self, center_hz: float, sample_rate: float,
                   gain: float, start_mhz: float, stop_mhz: float) -> None:
        """Continuous capture loop — runs in a background thread."""
        import json
        from core.sdr import SDRDevice, CaptureConfig
        from core.dsp import compute_psd, find_peaks

        CAPTURE_DURATION = 0.25
        DOWNSAMPLE_POINTS = 1024

        try:
            config = CaptureConfig(
                center_freq=center_hz,
                sample_rate=sample_rate,
                gain=gain,
                duration=CAPTURE_DURATION,
            )

            with SDRDevice() as sdr:
                while self._live_active:
                    capture = sdr.capture(config)
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

        except Exception as e:
            _emit("live", f"Live error: {e}")
            logger.error(traceback.format_exc())
        finally:
            self._live_active = False

    # ── Helpers ──────────────────────────────────────────

    @staticmethod
    def _downsample_2d(arr: np.ndarray, max_freq: int = 2048, max_time: int = 1024) -> np.ndarray:
        """Downsample a 2D array (freq x time) by block-averaging."""
        nf, nt = arr.shape
        step_f = max(1, nf // max_freq)
        step_t = max(1, nt // max_time)
        if step_f > 1 or step_t > 1:
            nf_trim = (nf // step_f) * step_f
            nt_trim = (nt // step_t) * step_t
            arr = arr[:nf_trim, :nt_trim]
            arr = arr.reshape(nf_trim // step_f, step_f, nt_trim // step_t, step_t).mean(axis=(1, 3))
        return arr

    def _render_waterfall_plot(self, data, params: dict, path: Path, peaks=None) -> None:
        from matplotlib.colors import Normalize

        freqs = data.freqs_mhz if hasattr(data, 'freqs_mhz') else data["freqs_mhz"]
        times = data.times if hasattr(data, 'times') else data["times"]
        power = data.power_db if hasattr(data, 'power_db') else data["power_db"]
        psd = data.mean_psd_db if hasattr(data, 'mean_psd_db') else data["mean_psd_db"]

        power_ds = self._downsample_2d(power, max_freq=2048, max_time=1024)
        nf_ds, nt_ds = power_ds.shape
        freqs_ds = np.linspace(freqs[0], freqs[-1], nf_ds)
        times_ds = np.linspace(times[0], times[-1], nt_ds)

        step_psd = max(1, len(psd) // 2048)
        psd_ds = psd[:len(psd) // step_psd * step_psd].reshape(-1, step_psd).mean(axis=1)
        freqs_psd = np.linspace(freqs[0], freqs[-1], len(psd_ds))

        fig, (ax_psd, ax_wf) = plt.subplots(
            2, 1, figsize=(14, 8),
            gridspec_kw={"height_ratios": [1, 3]}, sharex=True,
        )
        fig.patch.set_facecolor("#0a0e1a")

        for ax in (ax_psd, ax_wf):
            ax.set_facecolor("#0f1525")
            ax.tick_params(colors="#808080")
            ax.grid(True, alpha=0.15, color="#ffffff")
            for spine in ax.spines.values():
                spine.set_color("#2a2a3a")

        ax_psd.plot(freqs_psd, psd_ds, linewidth=0.8, color="#00d4ff")
        ax_psd.fill_between(freqs_psd, np.min(psd_ds), psd_ds, alpha=0.15, color="#00d4ff")

        if peaks:
            for pk in peaks:
                ax_psd.plot(pk.freq_mhz, pk.power_db, 'v', color='#ff6b35',
                            markersize=5, markeredgewidth=0.5)
                ax_psd.annotate(
                    f"{pk.freq_mhz:.3f}",
                    xy=(pk.freq_mhz, pk.power_db),
                    xytext=(0, 7), textcoords='offset points',
                    fontsize=5, color='#ff6b35', ha='center',
                    fontweight='bold',
                )

        ax_psd.set_ylabel("Power [dB]", color="#a0a0a0")

        n_peaks = len(peaks) if peaks else 0
        title = f"Waterfall — {params['start_mhz']:.1f}–{params['stop_mhz']:.1f} MHz"
        if n_peaks:
            title += f"  ({n_peaks} signal{'s' if n_peaks != 1 else ''})"
        ax_psd.set_title(title, color="#e0e0e0", fontsize=13, fontweight="bold")

        vmin = np.percentile(power_ds, 5)
        vmax = np.percentile(power_ds, 99)
        ax_wf.pcolormesh(
            freqs_ds, times_ds, power_ds.T,
            shading="auto", cmap="inferno",
            norm=Normalize(vmin=vmin, vmax=vmax),
        )
        ax_wf.set_ylabel("Time [s]", color="#a0a0a0")
        ax_wf.set_xlabel("Frequency [MHz]", color="#a0a0a0")

        plt.tight_layout()
        fig.savefig(path, dpi=150, facecolor=fig.get_facecolor())
        plt.close(fig)

        del power_ds, freqs_ds, times_ds, psd_ds, freqs_psd
        gc.collect()
