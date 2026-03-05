"""Shared feature extraction for training and inference.

12 channels total:
  Time-domain (from 100 kHz bandpass-filtered IQ):
    0: I
    1: Q
    2: Instantaneous frequency
    3: Amplitude envelope
    4: Instantaneous frequency variance (sliding window)
    5: Cyclostationary — FFT(|IQ|²)
  Multi-resolution spectrum (decimated IQ → FFT):
    6:  Full band (1.024 MHz)
    7:  200 kHz decimated
    8:  100 kHz decimated
    9:  25 kHz decimated
  Autocorrelation (bandpass-filtered IQ → ACF):
    10: Full band
    11: 200 kHz filtered
"""

from __future__ import annotations

import numpy as np
from scipy.signal import decimate as sp_decimate

N_CHANNELS = 12
N_IQ = 1024

ML_SAMPLE_RATE = 1.024e6

_FILTER_BW_HZ = (None, 200e3, 100e3, 25e3)

_INST_FREQ_VAR_WINDOW = 32


def _normalize(x: np.ndarray) -> np.ndarray:
    return ((x - x.mean()) / (x.std() + 1e-8)).astype(np.float32)


def _bandpass_filter(iq: np.ndarray, bw_hz: float, sample_rate: float) -> np.ndarray:
    """Bandpass filter IQ in frequency domain (no decimation, same length)."""
    n = len(iq)
    X = np.fft.fftshift(np.fft.fft(iq))
    freq_per_bin = sample_rate / n
    half_bins = int(bw_hz / 2 / freq_per_bin)
    center = n // 2
    mask = np.zeros(n, dtype=np.float32)
    mask[max(0, center - half_bins):min(n, center + half_bins + 1)] = 1.0
    return np.fft.ifft(np.fft.ifftshift(X * mask))


def _decimate_iq(iq: np.ndarray, bw_hz: float, sample_rate: float) -> np.ndarray:
    """Bandpass filter + decimate, then take/pad to N_IQ samples."""
    filtered = _bandpass_filter(iq, bw_hz, sample_rate)
    factor = max(1, int(round(sample_rate / bw_hz)))
    if factor >= 2:
        filtered = sp_decimate(filtered, factor, ftype="fir")
    n = len(filtered)
    if n >= N_IQ:
        start = (n - N_IQ) // 2
        return filtered[start:start + N_IQ]
    pad_total = N_IQ - n
    pad_l = pad_total // 2
    return np.pad(filtered, (pad_l, pad_total - pad_l), mode="constant")


def _spectrum(iq: np.ndarray) -> np.ndarray:
    X = np.fft.fftshift(np.fft.fft(iq, n=N_IQ))
    log_mag = 10 * np.log10(np.maximum(np.abs(X), 1e-12))
    return _normalize(log_mag)


def _autocorrelation(iq: np.ndarray) -> np.ndarray:
    X = np.fft.fft(iq, n=N_IQ)
    acf = np.fft.fftshift(np.abs(np.fft.ifft(X * np.conj(X))))
    return _normalize(acf)


def iq_to_channels(iq: np.ndarray, sample_rate: float = ML_SAMPLE_RATE) -> np.ndarray:
    """Convert complex IQ to (N_CHANNELS, N_IQ) float32 feature channels."""

    filt_iq = _bandpass_filter(iq, 100e3, sample_rate)

    i_ch = _normalize(filt_iq.real)
    q_ch = _normalize(filt_iq.imag)

    phase = np.unwrap(np.angle(filt_iq))
    inst_freq = np.diff(phase)
    inst_freq = np.append(inst_freq, inst_freq[-1])
    inst_freq_norm = _normalize(inst_freq)

    amp_norm = _normalize(np.abs(filt_iq))

    win = _INST_FREQ_VAR_WINDOW
    padded = np.pad(inst_freq, (win // 2, win // 2), mode="edge")
    cumsum = np.cumsum(padded)
    cumsum2 = np.cumsum(padded ** 2)
    window_mean = (cumsum[win:] - cumsum[:-win]) / win
    window_mean2 = (cumsum2[win:] - cumsum2[:-win]) / win
    inst_freq_var = (window_mean2 - window_mean ** 2)[:N_IQ]
    inst_freq_var_norm = _normalize(inst_freq_var)

    # Cyclostationary uses raw IQ so |IQ|² spectrum spans full bandwidth
    sq_mag = np.abs(iq) ** 2
    sq_mag = sq_mag - sq_mag.mean()
    cyclo = np.fft.fftshift(np.fft.fft(sq_mag, n=N_IQ))
    cyclo_norm = _normalize(np.log10(np.maximum(np.abs(cyclo), 1e-12)))

    spec_channels = []
    for bw_hz in _FILTER_BW_HZ:
        if bw_hz is None:
            raw_iq = iq
            if len(raw_iq) > N_IQ:
                s = (len(raw_iq) - N_IQ) // 2
                raw_iq = raw_iq[s:s + N_IQ]
            spec_channels.append(_spectrum(raw_iq))
        else:
            spec_channels.append(_spectrum(_decimate_iq(iq, bw_hz, sample_rate)))

    acf_full = _autocorrelation(iq[:N_IQ] if len(iq) > N_IQ else iq)
    acf_200k = _autocorrelation(_bandpass_filter(iq, 200e3, sample_rate))

    return np.stack([
        i_ch, q_ch,
        inst_freq_norm,
        amp_norm,
        inst_freq_var_norm,
        cyclo_norm,
        *spec_channels,
        acf_full,
        acf_200k,
    ])
