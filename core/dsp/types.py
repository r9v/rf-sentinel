"""DSP result types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class DemodMode(str, Enum):
    FM = "fm"
    AM = "am"


@dataclass
class SpectrumResult:
    """Power spectral density result."""
    freqs_mhz: np.ndarray
    power_db: np.ndarray
    center_freq_mhz: float
    sample_rate: float


@dataclass
class WaterfallResult:
    """Spectrogram / waterfall result."""
    freqs_mhz: np.ndarray
    times: np.ndarray
    power_db: np.ndarray       # 2D [freq x time] in dB
    mean_psd_db: np.ndarray    # Time-averaged PSD in dB
    center_freq_mhz: float
