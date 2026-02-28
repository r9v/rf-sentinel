"""SDR device interface — capture I/Q samples from RTL-SDR."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import logging

import numpy as np
from rtlsdr import RtlSdr

log = logging.getLogger(__name__)


@dataclass
class CaptureConfig:
    """Configuration for an SDR capture session."""

    center_freq: float  # Hz
    sample_rate: float = 1.024e6  # Hz
    gain: float = 30.0  # dB
    duration: float = 5.0  # seconds
    max_samples: int = 128 * 1024 * 1024  # ~1 GB limit (128M complex64 samples)


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
        self._last_config_key: Optional[tuple] = None

    def open(self) -> None:
        if self._sdr is None:
            self._sdr = RtlSdr()
            self._last_config_key = None

    def close(self) -> None:
        if self._sdr is not None:
            self._sdr.close()
            self._sdr = None
            self._last_config_key = None

    def __enter__(self) -> "SDRDevice":
        self.open()
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def _config_key(self, config: CaptureConfig) -> tuple:
        return (config.sample_rate, config.center_freq, config.gain)

    def capture(self, config: CaptureConfig) -> CaptureResult:
        """Capture I/Q samples based on config.

        Skips reconfiguration and PLL settling when config unchanged
        (for fast repeated captures in live mode). On first call or
        config change, applies full setup with PLL discard.
        """
        if self._sdr is None:
            raise RuntimeError("Device not open. Use 'with SDRDevice() as sdr:'")

        config_key = self._config_key(config)
        need_reconfig = config_key != self._last_config_key

        if need_reconfig:
            log.debug("SDR reconfig: sr=%.0f fc=%.0f gain=%.0f",
                      config.sample_rate, config.center_freq, config.gain)
            self._sdr.sample_rate = config.sample_rate
            self._sdr.center_freq = config.center_freq
            self._sdr.gain = config.gain

        num_samples = int(config.sample_rate * config.duration)
        if num_samples > config.max_samples:
            num_samples = config.max_samples

        actual_duration = num_samples / config.sample_rate

        if need_reconfig:
            try:
                self._sdr.read_samples(256 * 1024)
            except Exception as exc:
                self._last_config_key = None
                raise RuntimeError(
                    f"USB read failed on settle chunk (freq={config.center_freq/1e6:.1f} MHz, "
                    f"rate={config.sample_rate/1e6:.1f} MHz). "
                    "Device may need a replug."
                ) from exc
            self._last_config_key = config_key

        # Read in chunks to avoid memory spikes
        chunk_size = 256 * 1024
        chunks: list[np.ndarray] = []
        remaining = num_samples

        while remaining > 0:
            n = min(chunk_size, remaining)
            try:
                chunks.append(self._sdr.read_samples(n))
            except Exception as exc:
                log.error(
                    "USB read failed on chunk %d/%d (got %d/%d samples). "
                    "Device may need a replug.",
                    len(chunks) + 1,
                    -(-num_samples // chunk_size),
                    sum(len(c) for c in chunks),
                    num_samples,
                )
                raise
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
