"""DSP module — spectrum analysis, PSD, waterfall, and peak detection."""

from __future__ import annotations

import numpy as np
from scipy.signal import welch, spectrogram

from core.sdr import CaptureResult
from core.dsp.types import SpectrumResult, WaterfallResult, DemodMode  # noqa: F401
from core.dsp.peaks import SignalPeak, find_peaks                      # noqa: F401
from core.dsp.demod import demodulate, AUDIO_RATE                      # noqa: F401
from core.dsp.stitch import (                                 # noqa: F401
    SAMPLE_RATE, USABLE_BW_FRAC, STEP_HZ,
    plan_chunks, trim_spectrum, stitch_spectra,
    trim_waterfall, stitch_waterfalls,
)


def compute_psd(capture: CaptureResult, nfft: int = 4096) -> SpectrumResult:
    """Compute power spectral density using Welch method."""
    fs = capture.config.sample_rate
    fc = capture.config.center_freq

    freqs, psd = welch(capture.samples, fs=fs, nperseg=nfft, return_onesided=False)
    freqs = np.fft.fftshift(freqs)
    psd = np.fft.fftshift(psd)

    return SpectrumResult(
        freqs_mhz=(freqs + fc) / 1e6,
        power_db=10 * np.log10(psd + 1e-12),
        center_freq_mhz=fc / 1e6,
        sample_rate=fs,
    )


def compute_waterfall(capture: CaptureResult, nfft: int = 1024) -> WaterfallResult:
    """Compute spectrogram (waterfall) from captured I/Q samples."""
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

    power_db = 10 * np.log10(Sxx + 1e-12)

    return WaterfallResult(
        freqs_mhz=(freqs + fc) / 1e6,
        times=times,
        power_db=power_db,
        mean_psd_db=np.mean(power_db, axis=1),
        center_freq_mhz=fc / 1e6,
    )


def downsample_2d(arr: np.ndarray, max_freq: int = 2048, max_time: int = 1024) -> np.ndarray:
    """Downsample a 2D array (freq x time) by block-averaging."""
    nf, nt = arr.shape
    step_f = max(1, nf // max_freq)
    step_t = max(1, nt // max_time)
    if step_f > 1 or step_t > 1:
        nf_trim = (nf // step_f) * step_f
        nt_trim = (nt // step_t) * step_t
        arr = arr[:nf_trim, :nt_trim]
        arr = arr.reshape(nf_trim // step_f, step_f, nt_trim // step_t, step_t).mean(axis=(1, 3))
    return arr
