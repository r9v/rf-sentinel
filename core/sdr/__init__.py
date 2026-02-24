"""SDR device interface — capture I/Q samples from RTL-SDR."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from rtlsdr import RtlSdr


@dataclass
class CaptureConfig:
    """Configuration for an SDR capture session."""

    center_freq: float  # Hz
    sample_rate: float = 1.024e6  # Hz
    gain: float = 30.0  # dB
    duration: float = 5.0  # seconds
    max_samples: int = 5 * 1024 * 1024  # ~40 MB limit


@dataclass
class CaptureResult:
    """Result of a capture session with metadata."""

    samples: np.ndarray
    config: CaptureConfig
    actual_duration: float  # seconds
    num_samples: int

    @property
    def freq_mhz(self) -> float:
        return self.config.center_freq / 1e6


class SDRDevice:
    """Wrapper around RTL-SDR with resource management."""

    def __init__(self) -> None:
        self._sdr: Optional[RtlSdr] = None

    def open(self) -> None:
        if self._sdr is None:
            self._sdr = RtlSdr()

    def close(self) -> None:
        if self._sdr is not None:
            self._sdr.close()
            self._sdr = None

    def __enter__(self) -> "SDRDevice":
        self.open()
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def capture(self, config: CaptureConfig) -> CaptureResult:
        """Capture I/Q samples based on config.

        Automatically handles PLL settling (discards first chunk)
        and memory-safe chunked reading.
        """
        if self._sdr is None:
            raise RuntimeError("Device not open. Use 'with SDRDevice() as sdr:'")

        self._sdr.sample_rate = config.sample_rate
        self._sdr.center_freq = config.center_freq
        self._sdr.gain = config.gain

        num_samples = int(config.sample_rate * config.duration)
        if num_samples > config.max_samples:
            num_samples = config.max_samples

        actual_duration = num_samples / config.sample_rate

        # Discard first chunk — PLL settling
        self._sdr.read_samples(256 * 1024)

        # Read in chunks to avoid memory spikes
        chunk_size = 256 * 1024
        chunks: list[np.ndarray] = []
        remaining = num_samples

        while remaining > 0:
            n = min(chunk_size, remaining)
            chunks.append(self._sdr.read_samples(n))
            remaining -= n

        samples = np.concatenate(chunks)

        return CaptureResult(
            samples=samples,
            config=config,
            actual_duration=actual_duration,
            num_samples=len(samples),
        )

    def quick_capture(
        self, freq_mhz: float, duration: float = 5.0, **kwargs
    ) -> CaptureResult:
        """Convenience method — capture by frequency in MHz."""
        config = CaptureConfig(center_freq=freq_mhz * 1e6, duration=duration, **kwargs)
        return self.capture(config)
