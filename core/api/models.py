"""Pydantic models for the RFSentinel API."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from core.dsp.types import DemodMode


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"
    CANCELLED = "cancelled"


class ScanRequest(BaseModel):
    """Request to start a spectrum + waterfall scan over a frequency range."""
    start_mhz: float = Field(85.0, ge=24.0, le=1766.0)
    stop_mhz: float = Field(140.0, ge=24.0, le=1766.0)
    duration: float = Field(5.0, ge=0.5, le=30.0)
    gain: float = Field(30.0, ge=0.0, le=50.0)


class LiveRequest(BaseModel):
    """Request to start live spectrum monitoring."""
    start_mhz: float = Field(97.0, ge=24.0, le=1766.0)
    stop_mhz: float = Field(99.0, ge=24.0, le=1766.0)
    gain: float = Field(30.0, ge=0.0, le=50.0)
    audio_enabled: bool = Field(False, description="Enable audio demodulation")
    demod_mode: DemodMode = Field(DemodMode.FM, description="Demodulation mode: fm or am")


class RetuneRequest(BaseModel):
    """Retune live stream without restart."""
    start_mhz: float = Field(97.0, ge=24.0, le=1766.0)
    stop_mhz: float = Field(99.0, ge=24.0, le=1766.0)
    gain: float = Field(30.0, ge=0.0, le=50.0)


class AudioToggleRequest(BaseModel):
    """Toggle audio demod while live is running."""
    enabled: bool = Field(..., description="Enable or disable audio")
    demod_mode: DemodMode = Field(DemodMode.FM, description="Demodulation mode: fm or am")


class VfoRequest(BaseModel):
    """Set VFO frequency within the captured bandwidth."""
    freq_mhz: float = Field(..., ge=24.0, le=1766.0, description="VFO frequency in MHz")


class JobInfo(BaseModel):
    """Job status response."""
    id: str
    type: str
    status: JobStatus
    params: dict
    error: Optional[str] = None
    created_at: str
    duration_s: Optional[float] = None
