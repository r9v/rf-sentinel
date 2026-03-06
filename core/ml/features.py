"""Shared feature extraction for training and inference.

16 channels total:
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
    8:  Spectral delta — |spectrum(first half) - spectrum(second half)|, high for chirps
    9:  25 kHz decimated
  Autocorrelation (bandpass-filtered IQ → ACF):
    10: Full band
    11: 200 kHz filtered
  Modulation discrimination:
    12: Inst freq ACF — autocorrelation of inst freq, periodic peaks for LoRa/TDMA
    13: Envelope variance — sliding window variance of |IQ| (low for FM/NFM)
    14: Inst freq histogram — PMF of inst freq, Gaussian for FM, spikes for TDMA, flat for LoRa
    15: Sliding PAPR — peak-to-average power ratio in windows, low for FM/LoRa, high for OFDM/TDMA
"""

from __future__ import annotations

import numpy as np
from scipy.signal import decimate as sp_decimate

N_CHANNELS = 16
N_IQ = 1024

ML_SAMPLE_RATE = 1.024e6

_FILTER_BW_HZ = (None, 200e3, 25e3)

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


def _spectral_delta(iq: np.ndarray) -> np.ndarray:
    """Spectrum difference between first and second half of the signal.

    Chirps (LoRa) sweep frequency over time → large delta.
    Stationary signals (OFDM, FM) → near zero.
    """
    half = N_IQ // 2
    s1 = np.abs(np.fft.fftshift(np.fft.fft(iq[:half], n=N_IQ)))
    s2 = np.abs(np.fft.fftshift(np.fft.fft(iq[half:2 * half], n=N_IQ)))
    return _normalize(np.abs(s1 - s2))


def _envelope_variance(iq: np.ndarray, win: int = _INST_FREQ_VAR_WINDOW) -> np.ndarray:
    amp = np.abs(iq[:N_IQ]) if len(iq) > N_IQ else np.abs(iq)
    padded = np.pad(amp, (win // 2, win // 2), mode="edge")
    cs = np.cumsum(padded)
    cs2 = np.cumsum(padded ** 2)
    mu = (cs[win:] - cs[:-win]) / win
    mu2 = (cs2[win:] - cs2[:-win]) / win
    var = (mu2 - mu ** 2)[:N_IQ]
    return _normalize(var)


_HIST_BINS = 128


def _ifreq_acf(inst_freq: np.ndarray) -> np.ndarray:
    """Autocorrelation of instantaneous frequency — captures temporal periodicity.

    LoRa: strong periodic peaks (repeating chirps).
    TDMA: periodic structure at symbol/slot rate.
    FM/NFM: smooth decay (continuous modulation).
    OFDM: flat (random subcarrier phases).
    """
    vals = inst_freq[:N_IQ] if len(inst_freq) > N_IQ else inst_freq
    if len(vals) < N_IQ:
        vals = np.pad(vals, (0, N_IQ - len(vals)), mode="constant")
    X = np.fft.fft(vals, n=N_IQ)
    acf = np.fft.fftshift(np.abs(np.fft.ifft(X * np.conj(X))))
    return _normalize(acf)


def _ifreq_hist(inst_freq: np.ndarray) -> np.ndarray:
    """Instantaneous frequency distribution histogram (PMF interpolated to N_IQ).

    FM/NFM: Gaussian centered at carrier offset. TDMA: discrete spikes at symbol points.
    LoRa: flat rectangle (linear chirp sweep). Noise: wide uniform.
    """
    vals = inst_freq[:N_IQ] if len(inst_freq) > N_IQ else inst_freq
    if len(vals) < N_IQ:
        vals = np.pad(vals, (0, N_IQ - len(vals)), mode="constant")
    hist, _ = np.histogram(vals, bins=_HIST_BINS)
    hist = hist / (hist.sum() + 1e-8)
    x_old = np.linspace(0, 1, _HIST_BINS)
    x_new = np.linspace(0, 1, N_IQ)
    return np.interp(x_new, x_old, hist).astype(np.float32)


_PAPR_WINDOW = 32


def _papr_hist(iq: np.ndarray, win: int = _PAPR_WINDOW) -> np.ndarray:
    """Histogram of sliding-window PAPR values (PMF interpolated to N_IQ).

    FM/NFM: spike at 0 dB (constant envelope).
    OFDM: spread 3–10 dB (high PAPR, variable).
    TDMA: bimodal (low idle, high burst).
    LoRa: low spike (constant-envelope chirp).
    AM: moderate spread (varying envelope).
    """
    raw = iq[:N_IQ] if len(iq) > N_IQ else iq
    if len(raw) < N_IQ:
        raw = np.pad(raw, (0, N_IQ - len(raw)), mode="constant")
    power = np.abs(raw) ** 2
    padded = np.pad(power, (win // 2, win // 2), mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, win)
    peak = windows.max(axis=1)[:N_IQ]
    avg = windows.mean(axis=1)[:N_IQ]
    papr = peak / np.maximum(avg, 1e-12)
    papr_db = 10 * np.log10(np.maximum(papr, 1.0))
    hist, _ = np.histogram(papr_db, bins=_HIST_BINS, range=(0, 15))
    hist = hist / (hist.sum() + 1e-8)
    x_old = np.linspace(0, 1, _HIST_BINS)
    x_new = np.linspace(0, 1, N_IQ)
    return np.interp(x_new, x_old, hist).astype(np.float32)


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

    raw_iq = iq[:N_IQ] if len(iq) > N_IQ else iq

    spec_channels = [_spectrum(raw_iq)]
    for bw_hz in _FILTER_BW_HZ[1:]:
        spec_channels.append(_spectrum(_decimate_iq(iq, bw_hz, sample_rate)))

    spec_delta = _spectral_delta(raw_iq)

    acf_full = _autocorrelation(raw_iq)
    acf_200k = _autocorrelation(_bandpass_filter(iq, 200e3, sample_rate))

    ifreq_acf = _ifreq_acf(inst_freq)
    env_var = _envelope_variance(iq)
    ifreq_hist = _ifreq_hist(inst_freq)
    papr = _papr_hist(filt_iq)

    return np.stack([
        i_ch, q_ch,
        inst_freq_norm,
        amp_norm,
        inst_freq_var_norm,
        cyclo_norm,
        spec_channels[0],   # ch6: full band 1.024 MHz
        spec_channels[1],   # ch7: 200 kHz
        spec_delta,          # ch8: spectral delta
        spec_channels[2],   # ch9: 25 kHz
        acf_full,
        acf_200k,
        ifreq_acf,           # ch12: inst freq autocorrelation
        env_var,
        ifreq_hist,          # ch14: inst freq histogram
        papr,                # ch15: sliding-window PAPR
    ])
