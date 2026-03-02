"""Peak detection — find signals above the noise floor."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks as scipy_find_peaks


@dataclass
class SignalPeak:
    """A detected signal peak."""
    freq_mhz: float
    power_db: float
    prominence_db: float
    bandwidth_khz: float


def find_peaks(
    freqs_mhz: np.ndarray,
    power_db: np.ndarray,
    min_prominence_db: float = 8.0,
    min_distance_khz: float = 25.0,
    max_peaks: int = 30,
) -> list[SignalPeak]:
    """Find signal peaks in a power spectrum.

    Args:
        freqs_mhz: Frequency axis in MHz.
        power_db: Power values in dB.
        min_prominence_db: Minimum prominence above local noise floor.
        min_distance_khz: Minimum distance between peaks in kHz.
        max_peaks: Maximum number of peaks to return.

    Returns:
        List of SignalPeak sorted by power (strongest first).
    """
    freq_step_khz = (freqs_mhz[-1] - freqs_mhz[0]) / (len(freqs_mhz) - 1) * 1000
    min_distance_samples = max(1, int(min_distance_khz / freq_step_khz))

    indices, properties = scipy_find_peaks(
        power_db,
        prominence=min_prominence_db,
        distance=min_distance_samples,
        width=1,
    )

    if len(indices) == 0:
        return []

    prominences = properties["prominences"]
    widths = properties["widths"] * freq_step_khz

    peaks = [
        SignalPeak(
            freq_mhz=round(float(freqs_mhz[idx]), 4),
            power_db=round(float(power_db[idx]), 1),
            prominence_db=round(float(prom), 1),
            bandwidth_khz=round(float(w), 1),
        )
        for idx, prom, w in zip(indices, prominences, widths)
    ]

    peaks.sort(key=lambda p: p.power_db, reverse=True)
    return peaks[:max_peaks]
