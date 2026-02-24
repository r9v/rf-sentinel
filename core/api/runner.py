"""Background job runner — executes SDR tasks in threads and streams logs."""

from __future__ import annotations

import io
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
_log_callback: Optional[Callable[[str, str], None]] = None  # (job_id, message)


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

    def __init__(self, demo_mode: bool = False):
        self.demo_mode = demo_mode
        self.jobs: dict[str, Job] = {}
        self._pool = ThreadPoolExecutor(max_workers=1)  # One SDR at a time

    def submit_scan(self, freq_mhz: float, sample_rate_msps: float,
                    duration: float, gain: float) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(
            id=job_id,
            type="scan",
            status=JobStatus.PENDING,
            params={"freq_mhz": freq_mhz, "sample_rate_msps": sample_rate_msps,
                    "duration": duration, "gain": gain},
        )
        self.jobs[job_id] = job
        self._pool.submit(self._run_scan, job)
        return job

    def submit_waterfall(self, freq_mhz: float, sample_rate_msps: float,
                         duration: float, gain: float) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(
            id=job_id,
            type="waterfall",
            status=JobStatus.PENDING,
            params={"freq_mhz": freq_mhz, "sample_rate_msps": sample_rate_msps,
                    "duration": duration, "gain": gain},
        )
        self.jobs[job_id] = job
        self._pool.submit(self._run_waterfall, job)
        return job

    def submit_sweep(self, gain: float, bands: Optional[list[str]] = None) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(
            id=job_id,
            type="sweep",
            status=JobStatus.PENDING,
            params={"gain": gain, "bands": bands},
        )
        self.jobs[job_id] = job
        self._pool.submit(self._run_sweep, job)
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    def list_jobs(self, limit: int = 20) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)[:limit]

    # ── Scan ────────────────────────────────────────────

    def _run_scan(self, job: Job) -> None:
        job.status = JobStatus.RUNNING
        t0 = time.time()
        p = job.params

        try:
            _emit(job.id, f"Starting PSD scan: {p['freq_mhz']} MHz")
            _emit(job.id, f"  Rate: {p['sample_rate_msps']} Msps | Duration: {p['duration']}s | Gain: {p['gain']} dB")

            if self.demo_mode:
                result = self._demo_scan(p)
            else:
                result = self._real_scan(p)

            _emit(job.id, "Generating plot...")
            plot_path = PLOTS_DIR / f"scan_{job.id}.png"
            self._render_scan_plot(result, p, plot_path)

            job.result_path = plot_path
            job.status = JobStatus.COMPLETE
            job.duration_s = round(time.time() - t0, 2)
            _emit(job.id, f"Scan complete ({job.duration_s}s)")

        except Exception as e:
            job.status = JobStatus.ERROR
            job.error = str(e)
            job.duration_s = round(time.time() - t0, 2)
            _emit(job.id, f"ERROR: {e}")
            logger.error(traceback.format_exc())

    def _real_scan(self, p: dict) -> dict:
        from core.sdr import SDRDevice, CaptureConfig
        from core.dsp import compute_psd

        config = CaptureConfig(
            center_freq=p["freq_mhz"] * 1e6,
            sample_rate=p["sample_rate_msps"] * 1e6,
            duration=p["duration"],
            gain=p["gain"],
        )

        _emit("", "Opening SDR device...")
        with SDRDevice() as sdr:
            _emit("", "Capturing I/Q samples...")
            capture = sdr.capture(config)

        _emit("", f"Captured {capture.num_samples} samples ({capture.actual_duration:.2f}s)")
        _emit("", "Computing PSD (Welch method, NFFT=4096)...")
        result = compute_psd(capture)

        return {
            "freqs_mhz": result.freqs_mhz,
            "power_db": result.power_db,
            "center_freq_mhz": result.center_freq_mhz,
        }

    def _demo_scan(self, p: dict) -> dict:
        """Generate synthetic PSD data for demo/dev mode."""
        _emit("", "[DEMO] Generating synthetic RF data...")
        time.sleep(0.5)  # Simulate capture time

        fc = p["freq_mhz"]
        bw = p["sample_rate_msps"]
        n_points = 4096

        freqs_mhz = np.linspace(fc - bw / 2, fc + bw / 2, n_points)
        noise_floor = -45 + np.random.normal(0, 2, n_points)

        # Add some synthetic signals
        for offset in np.random.uniform(-bw / 3, bw / 3, size=np.random.randint(1, 5)):
            sig_freq = fc + offset
            sig_power = np.random.uniform(15, 35)
            sig_width = np.random.uniform(0.02, 0.15)
            noise_floor += sig_power * np.exp(-((freqs_mhz - sig_freq) ** 2) / (2 * sig_width ** 2))

        _emit("", f"[DEMO] Generated {n_points} points, {fc} MHz center")
        return {
            "freqs_mhz": freqs_mhz,
            "power_db": noise_floor,
            "center_freq_mhz": fc,
        }

    def _render_scan_plot(self, data: dict, params: dict, path: Path) -> None:
        fig, ax = plt.subplots(figsize=(14, 4))
        fig.patch.set_facecolor("#0a0e1a")
        ax.set_facecolor("#0f1525")

        freqs = data["freqs_mhz"]
        power = data["power_db"]

        ax.plot(freqs, power, linewidth=0.6, color="#00d4ff")
        ax.fill_between(freqs, np.min(power), power, alpha=0.15, color="#00d4ff")

        ax.set_xlabel("Frequency [MHz]", color="#a0a0a0")
        ax.set_ylabel("Power [dB]", color="#a0a0a0")
        ax.set_title(
            f"PSD — {data['center_freq_mhz']:.1f} MHz",
            color="#e0e0e0", fontsize=13, fontweight="bold",
        )
        ax.tick_params(colors="#808080")
        ax.grid(True, alpha=0.15, color="#ffffff")
        ax.set_xlim(freqs[0], freqs[-1])
        for spine in ax.spines.values():
            spine.set_color("#2a2a3a")

        plt.tight_layout()
        fig.savefig(path, dpi=150, facecolor=fig.get_facecolor())
        plt.close(fig)

    # ── Waterfall ───────────────────────────────────────

    def _run_waterfall(self, job: Job) -> None:
        job.status = JobStatus.RUNNING
        t0 = time.time()
        p = job.params

        try:
            _emit(job.id, f"Starting waterfall: {p['freq_mhz']} MHz")

            if self.demo_mode:
                data = self._demo_waterfall(p)
            else:
                data = self._real_waterfall(p)

            _emit(job.id, "Rendering waterfall plot...")
            plot_path = PLOTS_DIR / f"waterfall_{job.id}.png"
            self._render_waterfall_plot(data, p, plot_path)

            job.result_path = plot_path
            job.status = JobStatus.COMPLETE
            job.duration_s = round(time.time() - t0, 2)
            _emit(job.id, f"Waterfall complete ({job.duration_s}s)")

        except Exception as e:
            job.status = JobStatus.ERROR
            job.error = str(e)
            job.duration_s = round(time.time() - t0, 2)
            _emit(job.id, f"ERROR: {e}")
            logger.error(traceback.format_exc())

    def _real_waterfall(self, p: dict) -> dict:
        from core.sdr import SDRDevice, CaptureConfig
        from core.dsp import compute_waterfall

        config = CaptureConfig(
            center_freq=p["freq_mhz"] * 1e6,
            sample_rate=p["sample_rate_msps"] * 1e6,
            duration=p["duration"],
            gain=p["gain"],
        )

        _emit("", "Capturing I/Q for waterfall...")
        with SDRDevice() as sdr:
            capture = sdr.capture(config)

        _emit("", "Computing spectrogram...")
        result = compute_waterfall(capture)

        return {
            "freqs_mhz": result.freqs_mhz,
            "times": result.times,
            "power_db": result.power_db,
            "mean_psd_db": result.mean_psd_db,
            "center_freq_mhz": result.center_freq_mhz,
        }

    def _demo_waterfall(self, p: dict) -> dict:
        _emit("", "[DEMO] Generating synthetic waterfall...")
        time.sleep(0.8)

        fc = p["freq_mhz"]
        bw = p["sample_rate_msps"]
        n_freq = 512
        n_time = 200

        freqs_mhz = np.linspace(fc - bw / 2, fc + bw / 2, n_freq)
        times = np.linspace(0, p["duration"], n_time)

        power_db = np.random.normal(-45, 3, (n_freq, n_time))

        # Add persistent signals
        for _ in range(np.random.randint(1, 4)):
            sig_f = fc + np.random.uniform(-bw / 3, bw / 3)
            sig_w = np.random.uniform(0.02, 0.1)
            sig_p = np.random.uniform(10, 30)
            freq_profile = sig_p * np.exp(-((freqs_mhz - sig_f) ** 2) / (2 * sig_w ** 2))
            power_db += freq_profile[:, np.newaxis]

        # Add a burst signal
        burst_f = fc + np.random.uniform(-bw / 4, bw / 4)
        burst_t = np.random.randint(50, 150)
        burst_dur = np.random.randint(10, 40)
        freq_mask = np.exp(-((freqs_mhz - burst_f) ** 2) / (2 * 0.05 ** 2))
        power_db[:, burst_t:burst_t + burst_dur] += 20 * freq_mask[:, np.newaxis]

        mean_psd_db = np.mean(power_db, axis=1)

        return {
            "freqs_mhz": freqs_mhz,
            "times": times,
            "power_db": power_db,
            "mean_psd_db": mean_psd_db,
            "center_freq_mhz": fc,
        }

    def _render_waterfall_plot(self, data: dict, params: dict, path: Path) -> None:
        from matplotlib.colors import Normalize

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

        freqs = data["freqs_mhz"]
        psd = data["mean_psd_db"]
        ax_psd.plot(freqs, psd, linewidth=0.8, color="#00d4ff")
        ax_psd.fill_between(freqs, np.min(psd), psd, alpha=0.15, color="#00d4ff")
        ax_psd.set_ylabel("Power [dB]", color="#a0a0a0")
        ax_psd.set_title(
            f"Waterfall — {data['center_freq_mhz']:.1f} MHz",
            color="#e0e0e0", fontsize=13, fontweight="bold",
        )

        power = data["power_db"]
        vmin = np.percentile(power, 5)
        vmax = np.percentile(power, 99)

        im = ax_wf.pcolormesh(
            freqs, data["times"], power.T,
            shading="auto", cmap="inferno",
            norm=Normalize(vmin=vmin, vmax=vmax),
        )
        ax_wf.set_ylabel("Time [s]", color="#a0a0a0")
        ax_wf.set_xlabel("Frequency [MHz]", color="#a0a0a0")
        cbar = fig.colorbar(im, ax=ax_wf, label="Power [dB]", pad=0.01)
        cbar.ax.yaxis.set_tick_params(color="#808080")
        cbar.ax.yaxis.label.set_color("#a0a0a0")
        plt.setp(cbar.ax.yaxis.get_ticklabels(), color="#808080")

        plt.tight_layout()
        fig.savefig(path, dpi=150, facecolor=fig.get_facecolor())
        plt.close(fig)

    # ── Sweep ───────────────────────────────────────────

    def _run_sweep(self, job: Job) -> None:
        job.status = JobStatus.RUNNING
        t0 = time.time()
        p = job.params

        try:
            from core.plotting import BANDS
            band_keys = p.get("bands") or list(BANDS.keys())
            bands = [BANDS[k] for k in band_keys if k in BANDS]

            _emit(job.id, f"Starting sweep: {len(bands)} bands")

            results = []
            for band in bands:
                _emit(job.id, f"  Scanning: {band['name']}...")
                if self.demo_mode:
                    r = self._demo_scan({
                        "freq_mhz": band["freq"] / 1e6,
                        "sample_rate_msps": band["rate"] / 1e6,
                        "duration": 1.0,
                        "gain": p["gain"],
                    })
                else:
                    from core.sdr import SDRDevice, CaptureConfig
                    from core.dsp import compute_psd
                    config = CaptureConfig(
                        center_freq=band["freq"],
                        sample_rate=band["rate"],
                        duration=1.0,
                        gain=p["gain"],
                    )
                    with SDRDevice() as sdr:
                        capture = sdr.capture(config)
                    psd = compute_psd(capture)
                    r = {"freqs_mhz": psd.freqs_mhz, "power_db": psd.power_db,
                         "center_freq_mhz": psd.center_freq_mhz}
                results.append({"band": band, "data": r})

            _emit(job.id, "Rendering sweep plot...")
            plot_path = PLOTS_DIR / f"sweep_{job.id}.png"
            self._render_sweep_plot(results, plot_path)

            job.result_path = plot_path
            job.status = JobStatus.COMPLETE
            job.duration_s = round(time.time() - t0, 2)
            _emit(job.id, f"Sweep complete ({job.duration_s}s)")

        except Exception as e:
            job.status = JobStatus.ERROR
            job.error = str(e)
            job.duration_s = round(time.time() - t0, 2)
            _emit(job.id, f"ERROR: {e}")
            logger.error(traceback.format_exc())

    def _render_sweep_plot(self, results: list[dict], path: Path) -> None:
        n = len(results)
        fig, axes = plt.subplots(n, 1, figsize=(14, 2.5 * n))
        fig.patch.set_facecolor("#0a0e1a")

        if n == 1:
            axes = [axes]

        for i, entry in enumerate(results):
            ax = axes[i]
            ax.set_facecolor("#0f1525")
            data = entry["data"]

            ax.plot(data["freqs_mhz"], data["power_db"], linewidth=0.5, color="#00d4ff")
            ax.fill_between(data["freqs_mhz"], np.min(data["power_db"]),
                            data["power_db"], alpha=0.1, color="#00d4ff")
            ax.set_title(entry["band"]["name"], color="#e0e0e0", fontsize=11, fontweight="bold")
            ax.set_ylabel("dB", color="#a0a0a0")
            ax.tick_params(colors="#808080")
            ax.grid(True, alpha=0.15, color="#ffffff")
            ax.set_xlim(data["freqs_mhz"][0], data["freqs_mhz"][-1])
            for spine in ax.spines.values():
                spine.set_color("#2a2a3a")

        axes[-1].set_xlabel("Frequency [MHz]", color="#a0a0a0")
        plt.tight_layout()
        fig.savefig(path, dpi=150, facecolor=fig.get_facecolor())
        plt.close(fig)
