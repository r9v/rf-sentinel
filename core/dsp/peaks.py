"""Signal detection: adaptive noise floor, threshold-then-segment, temporal EMA."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import percentile_filter


@dataclass
class SignalPeak:
    """A detected signal."""
    freq_mhz: float
    power_db: float
    prominence_db: float
    bandwidth_khz: float
    transient: bool = False


NOISE_WINDOW_BINS = 501
NOISE_PERCENTILE = 25
MIN_SNR_DB = 5.0
MIN_SEGMENT_BINS = 1
MAX_GAP_KHZ = 50.0
MAX_SIGNAL_BW_KHZ = 300.0


def _estimate_noise_floor(power_db: np.ndarray) -> np.ndarray:
    """Estimate local noise floor using rolling percentile filter."""
    window = min(NOISE_WINDOW_BINS, len(power_db) // 2 * 2 + 1)
    if window < 3:
        return np.full_like(power_db, np.percentile(power_db, NOISE_PERCENTILE))
    return percentile_filter(power_db, percentile=NOISE_PERCENTILE, size=window, mode="reflect")


PEAKS_PER_MHZ = 5


def find_peaks(
    freqs_mhz: np.ndarray,
    power_db: np.ndarray,
    min_snr_db: float = MIN_SNR_DB,
    max_peaks: int = 0,
) -> list[SignalPeak]:
    """Detect signals using threshold-then-segment.

    1. Estimate adaptive noise floor (rolling median).
    2. Threshold: mark bins where power > noise + min_snr_db.
    3. Find contiguous regions of above-threshold bins.
    4. Each region = one signal.  Report peak power, center freq,
       SNR, and bandwidth from the region boundaries.

    max_peaks=0 (default) auto-scales based on bandwidth.
    """
    if len(freqs_mhz) < 4:
        return []

    freq_step_khz = float((freqs_mhz[-1] - freqs_mhz[0]) / (len(freqs_mhz) - 1) * 1000)
    bw_mhz = float(freqs_mhz[-1] - freqs_mhz[0])

    if max_peaks <= 0:
        max_peaks = max(50, int(bw_mhz * PEAKS_PER_MHZ))

    noise_floor = _estimate_noise_floor(power_db)
    excess_db = power_db - noise_floor

    above = excess_db >= min_snr_db

    # Find contiguous regions via diff
    padded = np.concatenate(([False], above, [False]))
    edges = np.diff(padded.astype(np.int8))
    starts = np.where(edges == 1)[0]
    stops = np.where(edges == -1)[0]

    if len(starts) == 0:
        return []

    # Drop narrow noise spikes (< MIN_SEGMENT_BINS wide)
    wide = np.array(stops) - np.array(starts) >= MIN_SEGMENT_BINS
    starts = starts[wide]
    stops = stops[wide]
    if len(starts) == 0:
        return []

    # Merge segments separated by small gaps (e.g. FM modulation dips),
    # but cap total width so dense bands don't chain into one mega-segment
    max_gap_bins = max(1, int(MAX_GAP_KHZ / freq_step_khz))
    max_bw_bins = int(MAX_SIGNAL_BW_KHZ / freq_step_khz)
    merged_starts = [starts[0]]
    merged_stops = [stops[0]]
    for i in range(1, len(starts)):
        gap_ok = starts[i] - merged_stops[-1] <= max_gap_bins
        width_ok = stops[i] - merged_starts[-1] <= max_bw_bins
        if gap_ok and width_ok:
            merged_stops[-1] = stops[i]
        else:
            merged_starts.append(starts[i])
            merged_stops.append(stops[i])

    peaks: list[SignalPeak] = []
    for lo, hi in zip(merged_starts, merged_stops):
        peak_idx = lo + int(np.argmax(power_db[lo:hi]))

        bw_khz = (hi - lo) * freq_step_khz
        snr = float(excess_db[peak_idx])

        peaks.append(SignalPeak(
            freq_mhz=round(float(freqs_mhz[peak_idx]), 4),
            power_db=round(float(power_db[peak_idx]), 1),
            prominence_db=round(snr, 1),
            bandwidth_khz=round(bw_khz, 1),
        ))

    peaks.sort(key=lambda p: p.prominence_db, reverse=True)
    return peaks[:max_peaks]


MERGE_PROXIMITY_KHZ = 50.0
MAXHOLD_MIN_SNR_DB = 8.0
MAXHOLD_MIN_DUTY = 0.05  # peak must appear in >=5% of time frames


def find_maxhold_peaks(
    freqs_mhz: np.ndarray,
    waterfall_db: np.ndarray,
    existing: list[SignalPeak],
    min_snr_db: float = MAXHOLD_MIN_SNR_DB,
) -> list[SignalPeak]:
    """Find peaks in max-hold PSD that aren't already in the existing list.

    Catches brief/intermittent transmissions that get averaged out in the
    mean PSD.  Validates that each candidate appears above the noise floor
    in multiple time frames to reject single-frame noise spikes.
    Returns combined list (existing + new max-hold-only peaks).
    """
    n_time = waterfall_db.shape[1]
    if n_time < 2:
        return existing

    max_psd = np.max(waterfall_db, axis=1)
    candidates = find_peaks(freqs_mhz, max_psd, min_snr_db=min_snr_db)

    if not candidates:
        return existing

    # Temporal validation: check each candidate has energy in multiple frames
    noise_floor = _estimate_noise_floor(np.mean(waterfall_db, axis=1))
    min_frames = max(2, int(n_time * MAXHOLD_MIN_DUTY))
    validated = []
    freq_step = float(freqs_mhz[1] - freqs_mhz[0]) if len(freqs_mhz) > 1 else 1.0
    for pk in candidates:
        idx = int(round((pk.freq_mhz - freqs_mhz[0]) / freq_step))
        idx = max(0, min(idx, len(freqs_mhz) - 1))
        # count frames where this bin exceeds noise + threshold
        frames_above = int(np.sum(waterfall_db[idx, :] > noise_floor[idx] + MIN_SNR_DB))
        if frames_above >= min_frames:
            validated.append(pk)

    if not validated:
        return existing
    if not existing:
        return validated

    existing_freqs = np.array([p.freq_mhz for p in existing])
    merged = list(existing)
    for pk in validated:
        dists = np.abs(existing_freqs - pk.freq_mhz) * 1000  # MHz -> kHz
        if np.min(dists) > MERGE_PROXIMITY_KHZ:
            pk.transient = True
            merged.append(pk)

    merged.sort(key=lambda p: p.prominence_db, reverse=True)
    return merged


class PsdSmoother:
    """Exponential moving average over consecutive PSD frames (live mode)."""

    def __init__(self, alpha: float = 0.3) -> None:
        self._alpha = alpha
        self._prev: np.ndarray | None = None

    def update(self, power_db: np.ndarray) -> np.ndarray:
        if self._prev is None or len(self._prev) != len(power_db):
            self._prev = power_db.copy()
            return power_db
        self._prev[:] = self._alpha * power_db + (1 - self._alpha) * self._prev
        return self._prev.copy()

    def reset(self) -> None:
        self._prev = None
