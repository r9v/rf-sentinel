"""Live mode — continuous SDR streaming with spectrum + audio."""

from __future__ import annotations

import json
import logging
import threading
import traceback
from typing import Callable, Optional

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
        self._vfo_freq_hz = freq_mhz * 1e6
        self._reset_dsp_state()
        self._emit("live", f"VFO → {freq_mhz:.3f} MHz")

    # ── Internal ──────────────────────────────────────────

    def _process_frame(self, capture, sample_rate: float,
                       frame_count: int, send_spectrum: bool) -> None:
        from core.dsp import demodulate
        from core.dsp.demod import vfo_shift

        if self._audio_enabled:
            try:
                iq = capture.samples
                if self._vfo_freq_hz is not None and self._config:
                    offset_hz = self._vfo_freq_hz - self._config.center_freq
                    if self._demod_state is None:
                        from core.dsp.demod import DemodState
                        self._demod_state = DemodState()
                    iq, self._demod_state.vfo_phase = vfo_shift(
                        iq, offset_hz, sample_rate, self._demod_state.vfo_phase,
                    )
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
