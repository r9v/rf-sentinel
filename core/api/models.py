"""Pydantic models for the RFSentinel API."""

from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"


class ScanRequest(BaseModel):
    """Request to start a PSD scan."""
    freq_mhz: float = Field(98.0, ge=24.0, le=1766.0, description="Center frequency in MHz")
    sample_rate_msps: float = Field(1.024, ge=0.25, le=2.56, description="Sample rate in Msps")
    duration: float = Field(2.0, ge=0.1, le=30.0, description="Capture duration in seconds")
    gain: float = Field(30.0, ge=0.0, le=50.0, description="SDR gain in dB")


class WaterfallRequest(BaseModel):
    """Request to start a waterfall capture."""
    freq_mhz: float = Field(98.0, ge=24.0, le=1766.0)
    sample_rate_msps: float = Field(1.024, ge=0.25, le=2.56)
    duration: float = Field(5.0, ge=0.5, le=30.0)
    gain: float = Field(30.0, ge=0.0, le=50.0)


class SweepRequest(BaseModel):
    """Request to start a multi-band sweep."""
    gain: float = Field(30.0, ge=0.0, le=50.0)
    bands: Optional[list[str]] = None  # None = all bands


class JobInfo(BaseModel):
    """Job status response."""
    id: str
    type: str
    status: JobStatus
    params: dict
    result_url: Optional[str] = None
    error: Optional[str] = None
    created_at: str
    duration_s: Optional[float] = None
