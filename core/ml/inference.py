"""ONNX-based signal classifier for live-mode peak classification."""

from __future__ import annotations

import logging
import os
import time

import numpy as np
from scipy.signal import decimate

from .features import ML_SAMPLE_RATE, N_IQ, iq_to_channels
from .model import ML_CLASSES

logger = logging.getLogger("rfsentinel.ml")

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "models", "classifier.onnx")

DEBUG_DIR = os.path.join("data", "debug")
_debug_count = 0
_DEBUG_MAX = 20
_capture_enabled = False
_capture_vfo_hz: float | None = None
_capture_label: str = "live"
_capture_last_time: float = 0.0
_CAPTURE_INTERVAL_S = 2.0


def enable_capture(count: int = 20, vfo_freq_hz: float | None = None, label: str = "live"):
    global _debug_count, _DEBUG_MAX, _capture_enabled, _capture_vfo_hz, _capture_label
    _debug_count = 0
    _DEBUG_MAX = count
    _capture_enabled = True
    _capture_vfo_hz = vfo_freq_hz
    _capture_label = label or "live"
    logger.info("Snippet capture enabled: %d snippets, label=%s, vfo=%.3f MHz",
                count, _capture_label, vfo_freq_hz / 1e6 if vfo_freq_hz else 0)


def disable_capture():
    global _capture_enabled
    _capture_enabled = False
    logger.info("Snippet capture disabled (captured %d)", _debug_count)


def capture_active() -> bool:
    return _capture_enabled and _debug_count < _DEBUG_MAX


def _extract_snippet(
    iq: np.ndarray,
    sample_rate: float,
    center_freq_hz: float,
    peak_freq_hz: float,
    bandwidth_hz: float = 200e3,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Extract feature channels + normalized IQ for one peak."""
    offset_hz = peak_freq_hz - center_freq_hz
    if abs(offset_hz) > 1e-3:
        t = np.arange(len(iq)) / sample_rate
        shifted = iq * np.exp(-1j * 2 * np.pi * offset_hz * t)
    else:
        shifted = iq

    if sample_rate > ML_SAMPLE_RATE * 1.1:
        factor = int(round(sample_rate / ML_SAMPLE_RATE))
        if factor >= 2:
            shifted = decimate(shifted, factor, ftype="fir")

    n = len(shifted)
    if n < N_IQ:
        return None

    start = (n - N_IQ) // 2
    snippet = shifted[start : start + N_IQ]

    power = np.mean(np.abs(snippet) ** 2)
    if power < 1e-12:
        return None
    snippet = snippet / np.sqrt(power)

    channels = iq_to_channels(snippet)
    return channels, snippet


def _dump_snippet(iq: np.ndarray, channels: np.ndarray, freq_hz: float, power_db: float):
    os.makedirs(DEBUG_DIR, exist_ok=True)
    freq_mhz = freq_hz / 1e6
    ts = int(time.time())
    path = os.path.join(DEBUG_DIR, f"{_capture_label}_{ts}_{freq_mhz:.2f}MHz_{power_db:.0f}dB.npz")
    np.savez_compressed(path, iq=iq, channels=channels, freq_mhz=freq_mhz)
    logger.info("Debug snippet saved: %s", path)


def _maybe_dump_snippet(snippet_data: list[tuple[np.ndarray, np.ndarray, float, float]]):
    global _debug_count, _capture_last_time
    if not _capture_enabled or _debug_count >= _DEBUG_MAX or not snippet_data:
        return
    now = time.time()
    if now - _capture_last_time < _CAPTURE_INTERVAL_S:
        return
    _capture_last_time = now
    if _capture_vfo_hz is not None:
        best = min(snippet_data, key=lambda s: abs(s[2] - _capture_vfo_hz))
    else:
        best = snippet_data[0]
    snippet_iq, channels, freq_hz, power_db = best
    _dump_snippet(snippet_iq, channels, freq_hz, power_db)
    _debug_count += 1
    if _debug_count >= _DEBUG_MAX:
        disable_capture()


class SignalClassifier:
    """Loads an ONNX model once and provides batched inference for peaks."""

    def __init__(self, model_path: str = MODEL_PATH) -> None:
        self._session = None
        self._input_name = "iq"
        try:
            import onnxruntime as ort
        except ImportError:
            logger.debug("onnxruntime not installed — ML classification disabled")
            return
        if not os.path.isfile(model_path):
            logger.debug("Model not found at %s — ML classification disabled", model_path)
            return
        self._session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self._input_name = self._session.get_inputs()[0].name
        logger.info("ML classifier loaded: %s", model_path)

    @property
    def available(self) -> bool:
        return self._session is not None

    def classify(
        self,
        iq_samples: np.ndarray,
        sample_rate: float,
        center_freq_hz: float,
        peak_freqs_hz: list[float],
        peak_bws_hz: list[float] | None = None,
        peak_powers_db: list[float] | None = None,
    ) -> list[tuple[str, float] | None] | None:
        """Classify peaks via ONNX. Returns (class_name, confidence) per peak, or None on failure."""
        if peak_bws_hz is None:
            peak_bws_hz = [200e3] * len(peak_freqs_hz)
        if peak_powers_db is None:
            peak_powers_db = [0.0] * len(peak_freqs_hz)
        try:
            tensors = []
            indices = []
            snippet_data = []
            for i, (pf, bw, pdb) in enumerate(zip(peak_freqs_hz, peak_bws_hz, peak_powers_db)):
                result = _extract_snippet(iq_samples, sample_rate, center_freq_hz, pf, bw)
                if result is not None:
                    channels, snippet_iq = result
                    tensors.append(channels)
                    indices.append(i)
                    snippet_data.append((snippet_iq, channels, pf, pdb))

            if not tensors:
                return None

            _maybe_dump_snippet(snippet_data)

            if not self._session:
                return None

            batch = np.stack(tensors)  # (N, N_CHANNELS, N_IQ)
            logits = self._session.run(None, {self._input_name: batch})[0]

            shifted = logits - logits.max(axis=1, keepdims=True)
            exp = np.exp(shifted)
            probs = exp / exp.sum(axis=1, keepdims=True)

            results: list[tuple[str, float] | None] = [None] * len(peak_freqs_hz)
            for j, idx in enumerate(indices):
                cls_idx = int(np.argmax(probs[j]))
                results[idx] = (ML_CLASSES[cls_idx], float(probs[j, cls_idx]))

            return results

        except Exception:
            logger.warning("ML classification failed", exc_info=True)
            return None


_classifier: SignalClassifier | None = None


def get_classifier() -> SignalClassifier:
    global _classifier
    if _classifier is None:
        _classifier = SignalClassifier()
    return _classifier
