"""Synthetic IQ dataset for signal classification training.

Generates realistic modulated signals using numpy/scipy. Each sample is a
(6, 4096) tensor at 1.024 MHz sample rate (~4 ms), normalized to unit power,
with random SNR, frequency offset, and phase rotation.

Channels: I, Q, log-magnitude spectrum, instantaneous frequency,
amplitude envelope, autocorrelation magnitude.
"""

from __future__ import annotations

import numpy as np
import torch
from torch.utils.data import Dataset

from .features import iq_to_channels
from .model import ML_CLASSES, N_CLASSES

SAMPLE_RATE = 1.024e6
N_IQ = 4096

# Bandwidth ranges per class (Hz) — realistic for RTL-SDR captures
_BW_RANGES: dict[str, tuple[float, float]] = {
    "fm": (100e3, 200e3),
    "am": (5e3, 10e3),
    "nfm": (5e3, 25e3),
    "digital": (10e3, 200e3),
    "noise": (0, 0),
}

# Digital modulation constellation maps
_CONSTELLATIONS = {
    "bpsk": np.array([-1 + 0j, 1 + 0j]),
    "qpsk": np.exp(1j * np.pi * np.array([0.25, 0.75, 1.25, 1.75])),
    "8psk": np.exp(1j * 2 * np.pi * np.arange(8) / 8),
    "16qam": np.array([
        a + b * 1j for a in [-3, -1, 1, 3] for b in [-3, -1, 1, 3]
    ]) / np.sqrt(10),
}


def _add_noise(iq: np.ndarray, snr_db: float) -> np.ndarray:
    sig_power = np.mean(np.abs(iq) ** 2)
    noise_power = sig_power * 10 ** (-snr_db / 10)
    noise = np.sqrt(noise_power / 2) * (
        np.random.randn(len(iq)) + 1j * np.random.randn(len(iq))
    )
    return iq + noise


def _normalize(iq: np.ndarray) -> np.ndarray:
    power = np.mean(np.abs(iq) ** 2)
    if power < 1e-12:
        return iq
    return iq / np.sqrt(power)


def _freq_shift(iq: np.ndarray, offset_hz: float) -> np.ndarray:
    if offset_hz == 0:
        return iq
    t = np.arange(len(iq)) / SAMPLE_RATE
    return iq * np.exp(1j * 2 * np.pi * offset_hz * t)


def _bandlimit(signal: np.ndarray, cutoff_hz: float) -> np.ndarray:
    """Simple FFT-based low-pass filter."""
    n = len(signal)
    freqs = np.fft.fftfreq(n, 1 / SAMPLE_RATE)
    spectrum = np.fft.fft(signal)
    spectrum[np.abs(freqs) > cutoff_hz] = 0
    return np.fft.ifft(spectrum)


def _gen_fm(rng: np.random.Generator, deviation_hz: float, audio_bw: float,
            stereo: bool = False) -> np.ndarray:
    audio = rng.standard_normal(N_IQ)
    audio = np.real(_bandlimit(audio, audio_bw))
    if stereo:
        # 19 kHz pilot tone (always present in real FM broadcast)
        t = np.arange(N_IQ) / SAMPLE_RATE
        pilot = 0.1 * np.sin(2 * np.pi * 19e3 * t)
        # L-R stereo difference on 38 kHz subcarrier (23-53 kHz)
        lr_audio = rng.standard_normal(N_IQ)
        lr_audio = np.real(_bandlimit(lr_audio, 15e3))
        lr_audio = lr_audio / (np.max(np.abs(lr_audio)) + 1e-10) * 0.5
        stereo_sub = lr_audio * np.sin(2 * np.pi * 38e3 * t)
        audio = audio + pilot + stereo_sub
    phase = 2 * np.pi * deviation_hz * np.cumsum(audio) / SAMPLE_RATE
    return np.exp(1j * phase).astype(np.complex64)


def _gen_am(rng: np.random.Generator, audio_bw: float) -> np.ndarray:
    audio = rng.standard_normal(N_IQ)
    audio = np.real(_bandlimit(audio, audio_bw))
    audio = audio / (np.max(np.abs(audio)) + 1e-10)
    mod_depth = rng.uniform(0.3, 0.9)
    envelope = 1.0 + mod_depth * audio
    return envelope.astype(np.complex64)


def _gen_digital(rng: np.random.Generator, symbol_rate: float) -> np.ndarray:
    name = rng.choice(list(_CONSTELLATIONS.keys()))
    constellation = _CONSTELLATIONS[name]
    samples_per_symbol = max(2, int(SAMPLE_RATE / symbol_rate))
    n_symbols = (N_IQ // samples_per_symbol) + 2
    symbols = constellation[rng.integers(0, len(constellation), n_symbols)]
    # Upsample with repeat (rectangular pulse shape)
    upsampled = np.repeat(symbols, samples_per_symbol)
    # Low-pass filter to smooth transitions
    cutoff = symbol_rate * 0.6
    filtered = _bandlimit(upsampled[:N_IQ + 256], cutoff)
    return filtered[:N_IQ].astype(np.complex64)


def _gen_noise(rng: np.random.Generator) -> np.ndarray:
    return (rng.standard_normal(N_IQ) + 1j * rng.standard_normal(N_IQ)).astype(np.complex64)


def generate_sample(class_idx: int, rng: np.random.Generator) -> np.ndarray:
    """Generate a single IQ sample for the given class index."""
    cls = ML_CLASSES[class_idx]
    bw_lo, bw_hi = _BW_RANGES[cls]

    if cls == "fm":
        deviation = rng.uniform(60e3, 80e3)
        stereo = rng.random() > 0.2  # 80% stereo, like real broadcast
        iq = _gen_fm(rng, deviation, audio_bw=15e3, stereo=stereo)
    elif cls == "am":
        iq = _gen_am(rng, audio_bw=rng.uniform(3e3, 5e3))
    elif cls == "nfm":
        deviation = rng.uniform(1e3, 5e3)
        iq = _gen_fm(rng, deviation, audio_bw=3e3)
    elif cls == "digital":
        symbol_rate = rng.uniform(2.4e3, 100e3)
        iq = _gen_digital(rng, symbol_rate)
    else:
        iq = _gen_noise(rng)

    # Augmentations
    if cls == "fm":
        snr_db = rng.uniform(5, 40)  # FM broadcast is typically strong
    else:
        snr_db = rng.uniform(-5, 30)
    iq = _add_noise(iq, snr_db) if cls != "noise" else iq

    freq_offset = rng.uniform(-SAMPLE_RATE * 0.05, SAMPLE_RATE * 0.05)
    iq = _freq_shift(iq, freq_offset)

    phase = rng.uniform(0, 2 * np.pi)
    iq = iq * np.exp(1j * phase)

    iq = _normalize(iq)
    return iq


class SignalDataset(Dataset):
    """Pre-generated dataset of labeled IQ snippets."""

    def __init__(self, samples_per_class: int = 10000, seed: int = 42):
        rng = np.random.default_rng(seed)
        total = samples_per_class * N_CLASSES
        self.data = np.empty((total, N_IQ), dtype=np.complex64)
        self.labels = np.empty(total, dtype=np.int64)

        idx = 0
        for cls_idx in range(N_CLASSES):
            for _ in range(samples_per_class):
                self.data[idx] = generate_sample(cls_idx, rng)
                self.labels[idx] = cls_idx
                idx += 1

    def __len__(self) -> int:
        return len(self.labels)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, int]:
        iq = self.data[idx]
        channels = iq_to_channels(iq)
        return torch.from_numpy(channels), int(self.labels[idx])
