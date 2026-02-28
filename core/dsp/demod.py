"""Audio demodulation — FM and AM demod from I/Q samples."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from core.dsp.types import DemodMode

AUDIO_RATE = 48_000
NARROWBAND_RATE = 200_000

# Headroom factor for int16 output (0→silence, 1→full scale, risk clipping)
HEADROOM = 0.9

# AM: EMA smoothing factor for peak normalization (0→no update, 1→instant)
AM_PEAK_EMA_ALPHA = 0.3


@dataclass
class DemodState:
    """Persistent state across demod frames for seamless audio."""
    last_iq_sample: Optional[complex] = None
    peak_ema: float = 0.0
    resample_phase: float = 0.0  # fractional input-sample position carried across frames


def demodulate(
    iq: np.ndarray,
    sample_rate: float,
    mode: DemodMode,
    state: Optional[DemodState] = None,
    audio_rate: int = AUDIO_RATE,
) -> tuple[np.ndarray, DemodState]:
    """Demodulate I/Q samples to int16 PCM audio.

    Pipeline: pre-decimate I/Q → demod → resample → normalize.
    Returns (int16 PCM array, updated state for next frame).
    """
    if state is None:
        state = DemodState()

    iq_narrow, narrow_rate = _pre_decimate_iq(iq, sample_rate)

    if mode == DemodMode.FM:
        baseband, last_sample = _fm_demod(iq_narrow, state.last_iq_sample)
    elif mode == DemodMode.AM:
        baseband = _am_demod(iq_narrow)
        last_sample = None
    else:
        raise ValueError(f"Unknown demod mode: {mode}")

    audio, new_phase = _resample_to_audio(baseband, narrow_rate, audio_rate, state.resample_phase)

    if mode == DemodMode.FM:
        pcm = _fm_to_int16(audio)
        new_peak = state.peak_ema
    else:
        pcm, new_peak = _am_to_int16(audio, state.peak_ema)

    new_state = DemodState(last_iq_sample=last_sample, peak_ema=new_peak, resample_phase=new_phase)
    return pcm, new_state


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


def _fm_demod(
    iq: np.ndarray, last_sample: Optional[complex] = None,
) -> tuple[np.ndarray, complex]:
    """FM discriminator with cross-frame phase continuity.

    Prepends last_sample from previous frame so the phase difference
    between frames is seamless (no click at frame boundaries).
    """
    if last_sample is not None:
        iq = np.concatenate(([last_sample], iq))
    product = iq[1:] * np.conj(iq[:-1])
    return np.angle(product), iq[-1]


def _am_demod(iq: np.ndarray) -> np.ndarray:
    """AM envelope detector with DC removal."""
    envelope = np.abs(iq)
    return envelope - np.mean(envelope)


def _resample_to_audio(
    signal: np.ndarray, from_rate: float, to_rate: int,
    phase: float = 0.0,
) -> tuple[np.ndarray, float]:
    """Linear-interpolation resample with fractional phase continuity.

    `phase` is the fractional input-sample offset carried from the previous
    frame so there's no timing discontinuity at frame boundaries.
    Returns (resampled audio, new phase for next frame).
    """
    ratio = from_rate / to_rate  # input samples per output sample
    n_in = len(signal)
    # How many output samples we can produce from this input
    n_out = int((n_in - phase) / ratio)
    if n_out <= 0:
        return np.zeros(0, dtype=signal.dtype), phase - n_in

    x_out = phase + np.arange(n_out) * ratio
    result = np.interp(x_out, np.arange(n_in), signal)

    # Phase for next frame: how far past the last input sample we've advanced
    new_phase = (phase + n_out * ratio) - n_in
    return result, new_phase


def _fm_to_int16(audio: np.ndarray) -> np.ndarray:
    """FM discriminator output is bounded to [-π, π] — use fixed scaling."""
    normed = audio * (HEADROOM / np.pi)
    return (normed * 32767).astype(np.int16)


def _am_to_int16(audio: np.ndarray, peak_ema: float = 0.0) -> tuple[np.ndarray, float]:
    """AM envelope has variable amplitude — use EMA-smoothed peak."""
    frame_peak = float(np.max(np.abs(audio)))
    if peak_ema <= 0:
        peak_ema = frame_peak
    else:
        peak_ema += AM_PEAK_EMA_ALPHA * (frame_peak - peak_ema)
    peak = max(peak_ema, 1e-10)
    normed = audio / peak * HEADROOM
    np.clip(normed, -1.0, 1.0, out=normed)
    return (normed * 32767).astype(np.int16), peak_ema
