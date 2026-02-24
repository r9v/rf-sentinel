"""DSP module — spectrum analysis, PSD, and waterfall generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.signal import welch, spectrogram

from core.sdr import CaptureResult


@dataclass
class SpectrumResult:
    """Power spectral density result."""

    freqs_mhz: np.ndarray  # Frequency axis in MHz
    power_db: np.ndarray  # Power in dB
    center_freq_mhz: float
    sample_rate: float


@dataclass
class WaterfallResult:
    """Spectrogram / waterfall result."""

    freqs_mhz: np.ndarray  # Frequency axis in MHz
    times: np.ndarray  # Time axis in seconds
    power_db: np.ndarray  # 2D power array [freq x time] in dB
    mean_psd_db: np.ndarray  # Time-averaged PSD in dB
    center_freq_mhz: float


def compute_psd(
    capture: CaptureResult,
    nfft: int = 4096,
) -> SpectrumResult:
    """Compute power spectral density using Welch method.

    Args:
        capture: CaptureResult from SDR device.
        nfft: FFT size (higher = better frequency resolution, slower).

    Returns:
        SpectrumResult with frequency and power arrays.
    """
    fs = capture.config.sample_rate
    fc = capture.config.center_freq

    freqs, psd = welch(capture.samples, fs=fs, nperseg=nfft, return_onesided=False)
    freqs = np.fft.fftshift(freqs)
    psd = np.fft.fftshift(psd)

    freqs_mhz = (freqs + fc) / 1e6
    power_db = 10 * np.log10(psd + 1e-12)

    return SpectrumResult(
        freqs_mhz=freqs_mhz,
        power_db=power_db,
        center_freq_mhz=fc / 1e6,
        sample_rate=fs,
    )


def compute_waterfall(
    capture: CaptureResult,
    nfft: int = 1024,
) -> WaterfallResult:
    """Compute spectrogram (waterfall) from captured I/Q samples.

    Args:
        capture: CaptureResult from SDR device.
        nfft: FFT size per time slice.

    Returns:
        WaterfallResult with 2D time-frequency power data.
    """
    fs = capture.config.sample_rate
    fc = capture.config.center_freq

    freqs, times, Sxx = spectrogram(
        capture.samples,
        fs=fs,
        nperseg=nfft,
        noverlap=nfft // 2,
        return_onesided=False,
        mode="psd",
    )

    freqs = np.fft.fftshift(freqs)
    Sxx = np.fft.fftshift(Sxx, axes=0)

    freqs_mhz = (freqs + fc) / 1e6
    power_db = 10 * np.log10(Sxx + 1e-12)
    mean_psd_db = np.mean(power_db, axis=1)

    return WaterfallResult(
        freqs_mhz=freqs_mhz,
        times=times,
        power_db=power_db,
        mean_psd_db=mean_psd_db,
        center_freq_mhz=fc / 1e6,
    )
