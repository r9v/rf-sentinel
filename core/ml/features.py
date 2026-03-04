"""Shared feature extraction for training and inference.

Channels: I, Q, log-magnitude spectrum, instantaneous frequency,
amplitude envelope, autocorrelation magnitude.
"""

from __future__ import annotations

import numpy as np

N_CHANNELS = 6


def iq_to_channels(iq: np.ndarray) -> np.ndarray:
    """Convert complex IQ to (6, N) float32 feature channels."""
    i_ch = iq.real.astype(np.float32)
    q_ch = iq.imag.astype(np.float32)

    # Log-magnitude spectrum (zero-mean, unit-variance)
    spectrum = np.fft.fftshift(np.fft.fft(iq))
    log_mag = 10 * np.log10(np.maximum(np.abs(spectrum), 1e-12))
    log_mag = (log_mag - log_mag.mean()) / (log_mag.std() + 1e-8)

    # Instantaneous frequency (derivative of unwrapped phase)
    phase = np.unwrap(np.angle(iq))
    inst_freq = np.diff(phase)
    inst_freq = np.append(inst_freq, inst_freq[-1])
    inst_freq = (inst_freq - inst_freq.mean()) / (inst_freq.std() + 1e-8)

    # Amplitude envelope
    amp = np.abs(iq)
    amp = (amp - amp.mean()) / (amp.std() + 1e-8)

    # Autocorrelation magnitude
    X = np.fft.fft(iq)
    acf = np.abs(np.fft.ifft(X * np.conj(X)))
    acf = (acf - acf.mean()) / (acf.std() + 1e-8)

    return np.stack([
        i_ch, q_ch,
        log_mag.astype(np.float32),
        inst_freq.astype(np.float32),
        amp.astype(np.float32),
        acf.astype(np.float32),
    ])
