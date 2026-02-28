"""Audio demodulation — FM and AM demod from I/Q samples."""

from __future__ import annotations

import numpy as np

from core.dsp.types import DemodMode

AUDIO_RATE = 48_000
NARROWBAND_RATE = 200_000


def demodulate(
    iq: np.ndarray,
    sample_rate: float,
    mode: DemodMode,
    audio_rate: int = AUDIO_RATE,
) -> np.ndarray:
    """Demodulate I/Q samples to int16 PCM audio.

    Pipeline: pre-decimate I/Q → demod → resample → normalize.
    Returns a numpy int16 array at the target audio_rate.
    """
    iq_narrow, narrow_rate = _pre_decimate_iq(iq, sample_rate)

    if mode == DemodMode.FM:
        baseband = _fm_demod(iq_narrow)
    elif mode == DemodMode.AM:
        baseband = _am_demod(iq_narrow)
    else:
        raise ValueError(f"Unknown demod mode: {mode}")

    audio = _resample_to_audio(baseband, narrow_rate, audio_rate)
    return _to_int16(audio)


def _pre_decimate_iq(
    iq: np.ndarray, sample_rate: float, target_rate: float = NARROWBAND_RATE,
) -> tuple[np.ndarray, float]:
    """Block-average decimate complex I/Q to narrowband. Very fast (pure numpy)."""
    factor = max(1, int(sample_rate / target_rate))
    if factor < 2:
        return iq, sample_rate
    n = (len(iq) // factor) * factor
    narrow = iq[:n].reshape(-1, factor).mean(axis=1)
    return narrow, sample_rate / factor


def _fm_demod(iq: np.ndarray) -> np.ndarray:
    """FM discriminator: instantaneous frequency from phase differences."""
    product = iq[1:] * np.conj(iq[:-1])
    return np.angle(product)


def _am_demod(iq: np.ndarray) -> np.ndarray:
    """AM envelope detector with DC removal."""
    envelope = np.abs(iq)
    return envelope - np.mean(envelope)


def _resample_to_audio(
    signal: np.ndarray, from_rate: float, to_rate: int,
) -> np.ndarray:
    """Fast linear-interpolation resample to exact audio rate."""
    n_out = int(len(signal) * to_rate / from_rate)
    if n_out == len(signal):
        return signal
    x_in = np.arange(len(signal))
    x_out = np.linspace(0, len(signal) - 1, n_out)
    return np.interp(x_out, x_in, signal)


def _to_int16(audio: np.ndarray) -> np.ndarray:
    """Normalize to int16 range with headroom."""
    peak = np.max(np.abs(audio))
    if peak > 0:
        audio = audio / peak * 0.9
    return (audio * 32767).astype(np.int16)
