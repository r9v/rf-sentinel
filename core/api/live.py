"""Live mode — continuous SDR streaming with spectrum + audio."""

from __future__ import annotations

import json
import logging
import os
import threading
import traceback
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

import numpy as np

from core.dsp.types import DemodMode

logger = logging.getLogger("rfsentinel.runner")

LIVE_PSD_NFFT = 2048
LIVE_FRAME_DURATION_S = 0.1
SPECTRUM_SEND_INTERVAL = 5
DOWNSAMPLE_POINTS = 1024


class LiveSession:
    """Owns all live-mode state and streaming logic."""

    def __init__(self, emit: Callable[[str, str], None],
                 emit_audio: Callable[[bytes], None]) -> None:
        self._emit = emit
        self._emit_audio = emit_audio
        self._active = False
        self._thread: threading.Thread | None = None
        self._sdr = None
        self._config = None
        self._audio_enabled = False
        self._demod_mode = DemodMode.FM
        self._demod_state = None
        self._vfo_freq_hz: Optional[float] = None
        self._peak_tracker = None
        self._psd_smoother = None
        self._rec_mode: Optional[str] = None
        self._rec_file = None
        self._rec_meta: dict = {}
        self._rec_bw: Optional[float] = None
        self._rec_samples: int = 0

    def _reset_dsp_state(self) -> None:
        self._demod_state = None
        self._peak_tracker = None
        self._psd_smoother = None

    @staticmethod
    def _compute_params(start_mhz: float, stop_mhz: float) -> tuple[float, float, float, float]:
        from core.dsp import SAMPLE_RATE
        max_bw = SAMPLE_RATE / 1e6
        if stop_mhz - start_mhz > max_bw:
            stop_mhz = start_mhz + max_bw
        center_hz = (start_mhz + stop_mhz) / 2 * 1e6
        bw_hz = (stop_mhz - start_mhz) * 1e6
        sample_rate = min(max(bw_hz, 0.25e6), SAMPLE_RATE)
        return center_hz, sample_rate, start_mhz, stop_mhz

    @property
    def active(self) -> bool:
        return self._active

    @property
    def audio_enabled(self) -> bool:
        return self._audio_enabled

    @property
    def vfo_freq_hz(self) -> Optional[float]:
        return self._vfo_freq_hz

    def start(self, start_mhz: float, stop_mhz: float, gain: float,
              audio_enabled: bool = False, demod_mode: DemodMode = DemodMode.FM) -> None:
        if self._active:
            self.stop()
        center_hz, sample_rate, start_mhz, stop_mhz = self._compute_params(start_mhz, stop_mhz)
        self._audio_enabled = audio_enabled
        self._demod_mode = demod_mode
        self._vfo_freq_hz = None
        self._reset_dsp_state()
        self._active = True
        self._thread = threading.Thread(
            target=self._loop,
            args=(center_hz, sample_rate, gain, start_mhz, stop_mhz),
            daemon=True,
        )
        self._thread.start()
        audio_tag = f" [audio: {demod_mode.upper()}]" if audio_enabled else ""
        self._emit("live", f"Live started: {start_mhz:.1f}–{stop_mhz:.1f} MHz{audio_tag}")

    def stop(self) -> None:
        if self._rec_mode:
            self.stop_recording()
        self._active = False
        self._audio_enabled = False
        if self._sdr:
            self._sdr.stop_stream()
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        self._sdr = None
        self._config = None
        self._emit("live", "Live stopped")

    def retune(self, start_mhz: float, stop_mhz: float, gain: float) -> None:
        if not self._active or not self._sdr:
            return
        from core.sdr import CaptureConfig
        center_hz, sample_rate, start_mhz, stop_mhz = self._compute_params(start_mhz, stop_mhz)
        if self._config and sample_rate != self._config.sample_rate:
            self._emit("live", "Sample rate changed — restarting stream")
            self.stop()
            self.start(start_mhz, stop_mhz, gain, self._audio_enabled, self._demod_mode)
            return
        self._sdr.retune(center_hz, gain)
        self._config = CaptureConfig(
            center_freq=center_hz, sample_rate=sample_rate,
            gain=gain, duration=0,
        )
        self._reset_dsp_state()
        logger.debug("retune: fc=%.3f MHz gain=%.0f dB", center_hz / 1e6, gain)

    def toggle_audio(self, enabled: bool, demod_mode: DemodMode = DemodMode.FM) -> None:
        self._audio_enabled = enabled
        self._demod_mode = demod_mode
        self._reset_dsp_state()
        state = f"ON ({demod_mode.upper()})" if enabled else "OFF"
        self._emit("live", f"Audio {state}")

    def set_vfo(self, freq_mhz: float) -> None:
        if self._rec_mode == "narrow":
            self.stop_recording()
        self._vfo_freq_hz = freq_mhz * 1e6
        self._reset_dsp_state()
        self._emit("live", f"VFO → {freq_mhz:.3f} MHz")

    @property
    def recording(self) -> Optional[str]:
        return self._rec_mode

    def start_recording(self, mode: str, bandwidth_khz: Optional[int] = None) -> dict:
        if self._rec_mode:
            self.stop_recording()
        if mode == "narrow" and self._vfo_freq_hz is None:
            raise ValueError("VFO must be set for narrowband recording")
        if mode == "narrow" and not bandwidth_khz:
            raise ValueError("bandwidth_khz required for narrowband recording")

        from core.api.db import RECORDINGS_DIR
        os.makedirs(RECORDINGS_DIR, exist_ok=True)

        rec_id = uuid.uuid4().hex[:12]
        ts = datetime.now(timezone.utc)
        ts_str = ts.strftime("%Y%m%d_%H%M%S")

        if mode == "narrow":
            freq_mhz = self._vfo_freq_hz / 1e6
            fname = f"{freq_mhz:.3f}MHz_{bandwidth_khz}kHz_{ts_str}.cf32"
        else:
            freq_mhz = self._config.center_freq / 1e6 if self._config else 0
            fname = f"{freq_mhz:.3f}MHz_wide_{ts_str}.cf32"

        filepath = RECORDINGS_DIR / fname
        self._rec_file = open(filepath, "wb")
        self._rec_mode = mode
        self._rec_bw = bandwidth_khz * 1e3 if bandwidth_khz else None
        self._rec_samples = 0
        self._rec_meta = {
            "id": rec_id,
            "mode": mode,
            "filename": fname,
            "freq_mhz": freq_mhz,
            "bandwidth_khz": bandwidth_khz,
            "sample_rate": (self._config.sample_rate if self._config else 0),
            "gain": (self._config.gain if self._config else 0),
            "start_mhz": 0,
            "stop_mhz": 0,
            "created_at": ts.isoformat(),
        }
        self._emit("live", f"Recording started: {mode} @ {freq_mhz:.3f} MHz")
        return {"id": rec_id, "mode": mode, "filename": fname}

    def stop_recording(self) -> Optional[dict]:
        if not self._rec_mode or not self._rec_file:
            return None
        self._rec_file.close()

        from core.api.db import RECORDINGS_DIR, save_recording
        filepath = RECORDINGS_DIR / self._rec_meta["filename"]
        file_size = filepath.stat().st_size if filepath.exists() else 0

        stopped_at = datetime.now(timezone.utc)
        created = datetime.fromisoformat(self._rec_meta["created_at"])
        duration_s = (stopped_at - created).total_seconds()

        if self._rec_mode == "narrow" and self._rec_bw and self._config:
            from core.dsp.record import decimate_iq
            factor = max(1, int(self._config.sample_rate // self._rec_bw))
            actual_rate = self._config.sample_rate / factor
        else:
            actual_rate = self._config.sample_rate if self._config else 0

        meta = {
            **self._rec_meta,
            "sample_rate": actual_rate,
            "num_samples": self._rec_samples,
            "file_size": file_size,
            "stopped_at": stopped_at.isoformat(),
            "duration_s": round(duration_s, 2),
        }
        if self._config:
            bw_mhz = self._config.sample_rate / 1e6
            center_mhz = self._config.center_freq / 1e6
            meta["start_mhz"] = round(center_mhz - bw_mhz / 2, 3)
            meta["stop_mhz"] = round(center_mhz + bw_mhz / 2, 3)

        save_recording(meta)
        self._emit("live", f"Recording saved: {self._rec_meta['filename']} "
                   f"({self._rec_samples} samples, {duration_s:.1f}s)")

        self._rec_mode = None
        self._rec_file = None
        self._rec_meta = {}
        self._rec_bw = None
        self._rec_samples = 0
        return meta

    # ── Internal ──────────────────────────────────────────

    def _process_frame(self, capture, sample_rate: float,
                       frame_count: int, send_spectrum: bool) -> None:
        from core.dsp import demodulate
        from core.dsp.demod import vfo_shift

        if self._rec_mode == "wide" and self._rec_file:
            try:
                data = capture.samples.astype(np.complex64).tobytes()
                self._rec_file.write(data)
                self._rec_samples += len(capture.samples)
            except Exception as e:
                logger.warning("wideband recording error: %s", e)

        vfo_iq = None
        if self._vfo_freq_hz is not None and self._config:
            offset_hz = self._vfo_freq_hz - self._config.center_freq
            if self._demod_state is None:
                from core.dsp.demod import DemodState
                self._demod_state = DemodState()
            vfo_iq, self._demod_state.vfo_phase = vfo_shift(
                capture.samples, offset_hz, sample_rate, self._demod_state.vfo_phase,
            )

        if self._rec_mode == "narrow" and self._rec_file and vfo_iq is not None:
            try:
                from core.dsp.record import decimate_iq
                decimated, _ = decimate_iq(vfo_iq, sample_rate, self._rec_bw)
                self._rec_file.write(decimated.tobytes())
                self._rec_samples += len(decimated)
            except Exception as e:
                logger.warning("narrowband recording error: %s", e)

        if self._audio_enabled:
            try:
                iq = vfo_iq if vfo_iq is not None else capture.samples
                mode = DemodMode(self._demod_mode)
                pcm, self._demod_state = demodulate(
                    iq, sample_rate, mode, self._demod_state,
                )
                self._emit_audio(pcm.tobytes())
            except Exception as e:
                logger.warning("audio demod error frame %d: %s", frame_count, e)

        if send_spectrum:
            self._send_spectrum(capture)

    def _send_spectrum(self, capture) -> None:
        from core.dsp import compute_psd, find_peaks
        from core.dsp.peaks import PsdSmoother
        from core.dsp.tracker import PeakTracker
        from core.dsp.classify import classify_peaks

        result = compute_psd(capture, nfft=LIVE_PSD_NFFT)

        if self._psd_smoother is None:
            self._psd_smoother = PsdSmoother()
        smoothed = self._psd_smoother.update(result.power_db)

        step = max(1, len(result.freqs_mhz) // DOWNSAMPLE_POINTS)
        freqs = result.freqs_mhz[::step]
        power = smoothed[::step]

        raw_peaks = find_peaks(result.freqs_mhz, smoothed)
        if self._peak_tracker is None:
            self._peak_tracker = PeakTracker()
        tracked = self._peak_tracker.update(raw_peaks, result.freqs_mhz, smoothed)
        classified = classify_peaks(result.freqs_mhz, smoothed, tracked)

        payload = json.dumps({
            "type": "spectrum",
            "freqs_mhz": freqs.tolist(),
            "power_db": power.tolist(),
            "peaks": classified,
            "recording": self._rec_mode,
        })
        self._emit("__spectrum__", payload)

    def _loop(self, center_hz: float, sample_rate: float,
              gain: float, start_mhz: float, stop_mhz: float) -> None:
        from core.sdr import SDRDevice, CaptureConfig, CaptureResult

        frame_count = 0
        try:
            with SDRDevice() as sdr:
                self._sdr = sdr
                self._config = CaptureConfig(
                    center_freq=center_hz, sample_rate=sample_rate,
                    gain=gain, duration=0,
                )
                sdr.configure(self._config)
                chunk_samples = int(sample_rate * LIVE_FRAME_DURATION_S)

                def on_chunk(iq):
                    nonlocal frame_count
                    if not self._active:
                        sdr.stop_stream()
                        return
                    cfg = self._config
                    capture = CaptureResult(
                        samples=iq, config=cfg,
                        actual_duration=len(iq) / cfg.sample_rate,
                        num_samples=len(iq),
                    )
                    send_spectrum = (frame_count % SPECTRUM_SEND_INTERVAL == 0)
                    self._process_frame(capture, cfg.sample_rate, frame_count, send_spectrum)
                    frame_count += 1

                sdr.start_stream(on_chunk, chunk_samples)
        except Exception as e:
            if self._active:
                self._emit("live", f"Live error: {e}")
                logger.error(traceback.format_exc())
        finally:
            self._active = False
            self._audio_enabled = False
            self._sdr = None
            self._config = None
            logger.debug("live loop exited after %d frames", frame_count)
