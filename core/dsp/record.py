"""IQ recording helpers — decimation for narrowband capture."""

from __future__ import annotations

import numpy as np
from scipy.signal import firwin, lfilter


def decimate_iq(iq: np.ndarray, sample_rate: float,
                target_bw: float) -> tuple[np.ndarray, float]:
    """Low-pass filter and decimate IQ to *target_bw* Hz bandwidth.

    Returns (decimated_iq, actual_sample_rate).
    """
    factor = max(1, int(sample_rate // target_bw))
    if factor <= 1:
        return iq.astype(np.complex64), sample_rate

    cutoff = target_bw / 2
    nyq = sample_rate / 2
    numtaps = min(63, factor * 8 + 1) | 1  # odd, reasonable length
    taps = firwin(numtaps, cutoff / nyq)

    filtered_i = lfilter(taps, 1.0, iq.real)
    filtered_q = lfilter(taps, 1.0, iq.imag)
    decimated = (filtered_i[::factor] + 1j * filtered_q[::factor]).astype(np.complex64)
    actual_rate = sample_rate / factor
    return decimated, actual_rate
