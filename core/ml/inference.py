"""ONNX-based signal classifier for live-mode peak classification."""

from __future__ import annotations

import logging
import os

import numpy as np

from .features import iq_to_channels
from .model import ML_CLASSES

logger = logging.getLogger("rfsentinel.ml")

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "models", "classifier.onnx")
ML_SAMPLE_RATE = 1.024e6
N_IQ = 4096


def _extract_snippet(
    iq: np.ndarray,
    sample_rate: float,
    center_freq_hz: float,
    peak_freq_hz: float,
) -> np.ndarray | None:
    """Extract a (6, N_IQ) float32 tensor for one peak from capture IQ.

    Freq-shifts to center the peak at DC, decimates to ML_SAMPLE_RATE if
    needed, normalizes to unit power, and builds feature channels
    matching the training pipeline via iq_to_channels().
    """
    offset_hz = peak_freq_hz - center_freq_hz
    if abs(offset_hz) > 1e-3:
        t = np.arange(len(iq)) / sample_rate
        shifted = iq * np.exp(-1j * 2 * np.pi * offset_hz * t)
    else:
        shifted = iq

    if sample_rate > ML_SAMPLE_RATE * 1.1:
        from scipy.signal import decimate
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

    return iq_to_channels(snippet)


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
    ) -> list[tuple[str, float] | None] | None:
        """Classify peaks via ONNX. Returns (class_name, confidence) per peak, or None on failure."""
        if not self._session:
            return None
        try:
            tensors = []
            indices = []
            for i, pf in enumerate(peak_freqs_hz):
                t = _extract_snippet(iq_samples, sample_rate, center_freq_hz, pf)
                if t is not None:
                    tensors.append(t)
                    indices.append(i)

            if not tensors:
                return None

            batch = np.stack(tensors)  # (N, 6, N_IQ)
            logits = self._session.run(None, {self._input_name: batch})[0]  # (N, 5)

            # Softmax
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
