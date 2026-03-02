"""Peak tracker — stabilise detections across live frames."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.dsp.peaks import SignalPeak


FREQ_TOLERANCE_KHZ = 25.0
CONFIRM_FRAMES = 3
DECAY_FRAMES = 8
FREQ_ALPHA = 0.3


@dataclass
class TrackedPeak:
    id: int
    freq_mhz: float
    power_db: float
    prominence_db: float
    bandwidth_khz: float
    hit_count: int = 1
    miss_count: int = 0

    @property
    def confirmed(self) -> bool:
        return self.hit_count >= CONFIRM_FRAMES


class PeakTracker:
    def __init__(self) -> None:
        self._tracks: list[TrackedPeak] = []
        self._next_id = 0

    def _new_id(self) -> int:
        tid = self._next_id
        self._next_id += 1
        return tid

    def update(self, peaks: list[SignalPeak]) -> list[TrackedPeak]:
        matched_tracks: set[int] = set()
        matched_peaks: set[int] = set()

        # Build distance pairs and sort by distance (greedy nearest-neighbor)
        pairs: list[tuple[float, int, int]] = []
        for ti, track in enumerate(self._tracks):
            for pi, peak in enumerate(peaks):
                dist_khz = abs(track.freq_mhz - peak.freq_mhz) * 1000
                if dist_khz <= FREQ_TOLERANCE_KHZ:
                    pairs.append((dist_khz, ti, pi))
        pairs.sort()

        for _, ti, pi in pairs:
            if ti in matched_tracks or pi in matched_peaks:
                continue
            track = self._tracks[ti]
            peak = peaks[pi]
            track.freq_mhz += FREQ_ALPHA * (peak.freq_mhz - track.freq_mhz)
            track.power_db = peak.power_db
            track.prominence_db = peak.prominence_db
            track.bandwidth_khz = peak.bandwidth_khz
            track.hit_count += 1
            track.miss_count = 0
            matched_tracks.add(ti)
            matched_peaks.add(pi)

        # New tracks for unmatched peaks
        for pi, peak in enumerate(peaks):
            if pi in matched_peaks:
                continue
            self._tracks.append(TrackedPeak(
                id=self._new_id(),
                freq_mhz=peak.freq_mhz,
                power_db=peak.power_db,
                prominence_db=peak.prominence_db,
                bandwidth_khz=peak.bandwidth_khz,
            ))

        # Age unmatched tracks, drop expired
        for ti, track in enumerate(self._tracks):
            if ti not in matched_tracks and track.hit_count > 0:
                track.miss_count += 1
        self._tracks = [t for t in self._tracks if t.miss_count <= DECAY_FRAMES]

        # Return only confirmed, sorted by power
        result = [t for t in self._tracks if t.confirmed]
        result.sort(key=lambda t: t.power_db, reverse=True)
        return result
