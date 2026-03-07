"""Rule-based signal classification from spectral features + band awareness."""

from __future__ import annotations

import numpy as np

from .bands import lookup_band

FM_BROADCAST = "fm_broadcast"
NARROWBAND_FM = "narrowband_fm"
OFDM = "ofdm"
TDMA = "tdma"
DIGITAL = "digital"
AM_BROADCAST = "am_broadcast"
CARRIER = "carrier"
LORA = "lora"
ADSB = "adsb"
AVIATION = "aviation"
HAM = "ham"
ISM = "ism"
UNKNOWN = "unknown"

SHORT_LABELS = {
    FM_BROADCAST: "FM",
    NARROWBAND_FM: "NFM",
    OFDM: "OFDM",
    TDMA: "TDMA",
    DIGITAL: "DIG",
    AM_BROADCAST: "AM",
    CARRIER: "CW",
    LORA: "LoRa",
    ADSB: "ADS-B",
    AVIATION: "AIR",
    HAM: "HAM",
    ISM: "ISM",
    UNKNOWN: "",
}


def _spectral_flatness(power_linear: np.ndarray) -> float:
    """Geometric mean / arithmetic mean of linear power. 0=tonal, 1=flat."""
    p = power_linear[power_linear > 0]
    if len(p) < 2:
        return 0.0
    log_mean = np.mean(np.log(p))
    return float(np.exp(log_mean) / np.mean(p))


def _occupied_bandwidth_khz(freqs_mhz: np.ndarray, power_linear: np.ndarray) -> float:
    """Bandwidth containing 99% of total power."""
    total = np.sum(power_linear)
    if total <= 0:
        return 0.0
    cumsum = np.cumsum(power_linear)
    lo = np.searchsorted(cumsum, total * 0.005)
    hi = np.searchsorted(cumsum, total * 0.995)
    lo = max(0, lo)
    hi = min(len(freqs_mhz) - 1, hi)
    return float((freqs_mhz[hi] - freqs_mhz[lo]) * 1000)


def _edge_steepness(power_db: np.ndarray, freq_step_khz: float) -> float:
    """Average slope at signal edges in dB/kHz."""
    n = len(power_db)
    if n < 6:
        return 0.0
    edge_bins = max(2, n // 8)
    left_slope = abs(power_db[edge_bins] - power_db[0]) / (edge_bins * freq_step_khz)
    right_slope = abs(power_db[-1] - power_db[-1 - edge_bins]) / (edge_bins * freq_step_khz)
    return float((left_slope + right_slope) / 2)


DUTY_CYCLE_THRESHOLD_DB = 3.0


def _temporal_features(
    freqs_mhz: np.ndarray,
    waterfall_db: np.ndarray,
    peak_freq_mhz: float,
    bw_khz: float,
) -> tuple[float, float]:
    """Extract duty_cycle and power_variance from 2D waterfall at a peak.

    waterfall_db: shape [freq x time] in dB.
    Returns (duty_cycle, power_variance_db).
    """
    n_freq = len(freqs_mhz)
    freq_step_mhz = (freqs_mhz[-1] - freqs_mhz[0]) / (n_freq - 1)
    center_idx = int(np.argmin(np.abs(freqs_mhz - peak_freq_mhz)))

    half_bw_bins = max(1, int(bw_khz / 2 / 1000 / freq_step_mhz))
    sig_lo = max(0, center_idx - half_bw_bins)
    sig_hi = min(n_freq, center_idx + half_bw_bins + 1)

    # Signal time series: mean power across peak's freq bins per time slice
    time_series = np.mean(waterfall_db[sig_lo:sig_hi, :], axis=0)

    if len(time_series) < 3:
        return 1.0, 0.0

    # Noise reference: median of neighboring freq bins outside the signal
    margin = max(half_bw_bins, 10)
    noise_lo = max(0, sig_lo - margin * 2)
    noise_hi = min(n_freq, sig_hi + margin * 2)
    # Exclude signal bins — take from left and right flanks
    left = waterfall_db[noise_lo:max(noise_lo, sig_lo - margin), :]
    right = waterfall_db[min(n_freq, sig_hi + margin):noise_hi, :]
    noise_bins = np.concatenate([left, right], axis=0) if left.size and right.size else (
        left if left.size else right
    )
    if noise_bins.size > 0:
        noise_level = float(np.median(noise_bins))
    else:
        noise_level = float(np.percentile(time_series, 10))

    above = time_series > noise_level + DUTY_CYCLE_THRESHOLD_DB
    duty_cycle = float(np.mean(above))
    power_var = float(np.var(time_series))

    return duty_cycle, power_var


def _apply_temporal(
    signal_type: str,
    confidence: float,
    duty_cycle: float,
    power_var: float,
    occ_bw: float,
    bw_khz: float,
    prominence: float,
) -> tuple[str, float]:
    """Reclassify using temporal features from waterfall data.

    Bursty/intermittent signals (low duty cycle, high variance) are likely
    voice comms (aviation, ham), not broadcast.  Continuous high-duty-cycle
    signals reinforce broadcast/digital classification.
    """
    # Very low duty cycle = intermittent transmission (PTT voice, bursty data)
    if duty_cycle < 0.4 and power_var > 5.0:
        if signal_type in (FM_BROADCAST, AM_BROADCAST, OFDM, TDMA, UNKNOWN):
            if occ_bw <= 35:
                return NARROWBAND_FM, 0.65
            return NARROWBAND_FM, 0.55

    # Moderate duty cycle with high variance = likely voice/intermittent
    if duty_cycle < 0.7 and power_var > 10.0:
        if signal_type == FM_BROADCAST and occ_bw < 100:
            return NARROWBAND_FM, 0.6

    # High duty cycle + low variance reinforces broadcast/digital
    if duty_cycle > 0.9 and power_var < 3.0:
        if signal_type == FM_BROADCAST:
            confidence = min(0.95, confidence + 0.05)
        elif signal_type in (OFDM, TDMA):
            confidence = min(0.90, confidence + 0.05)

    return signal_type, confidence


_NFM_COMPATIBLE = {AVIATION, HAM, ISM, NARROWBAND_FM, TDMA}


def _apply_band_prior(freq_mhz: float, signal_type: str, confidence: float) -> tuple[str, float, str | None]:
    """Adjust classification using frequency band knowledge.

    Returns (signal_type, confidence, band_name).
    """
    band = lookup_band(freq_mhz)
    if band is None:
        return signal_type, confidence, None

    expected = band.expected_type

    if signal_type == expected:
        return signal_type, min(0.98, confidence + 0.1), band.name

    if signal_type == UNKNOWN:
        return expected, 0.55, band.name

    # NFM is a generic narrowband voice/data type — promote to the band's
    # specific type when compatible (e.g. NFM on airband → aviation)
    if signal_type == NARROWBAND_FM and expected in _NFM_COMPATIBLE:
        return expected, min(0.90, confidence + 0.05), band.name

    # Spectral says one thing, band says another — trust spectral but note the band
    return signal_type, max(0.3, confidence - 0.1), band.name


def _classify_one(
    freqs_mhz: np.ndarray,
    power_db: np.ndarray,
    peak,
    waterfall_db: np.ndarray | None = None,
) -> dict:
    """Classify a single peak and return a dict with peak fields + classification."""
    freq_step_khz = float((freqs_mhz[-1] - freqs_mhz[0]) / (len(freqs_mhz) - 1) * 1000)

    bw_khz = getattr(peak, "bandwidth_khz", 0.0)
    prominence = getattr(peak, "prominence_db", 0.0)

    # Slice PSD around peak — wide enough to capture full FM broadcast signals
    window_khz = max(bw_khz * 4, 250.0)
    window_bins = max(4, int(window_khz / freq_step_khz / 2))
    center_idx = int(np.argmin(np.abs(freqs_mhz - peak.freq_mhz)))
    lo = max(0, center_idx - window_bins)
    hi = min(len(freqs_mhz), center_idx + window_bins + 1)

    sl_freqs = freqs_mhz[lo:hi]
    sl_db = power_db[lo:hi]
    sl_linear = 10.0 ** (sl_db / 10.0)

    flatness = _spectral_flatness(sl_linear)
    occ_bw = _occupied_bandwidth_khz(sl_freqs, sl_linear)
    steepness = _edge_steepness(sl_db, freq_step_khz)

    # Temporal features from waterfall (scan mode only)
    duty_cycle: float | None = None
    power_var: float | None = None
    if waterfall_db is not None and waterfall_db.shape[1] >= 3:
        duty_cycle, power_var = _temporal_features(
            freqs_mhz, waterfall_db, peak.freq_mhz, bw_khz,
        )

    # Rule-based spectral classification
    signal_type = UNKNOWN
    confidence = 0.5

    if (occ_bw > 120 and flatness > 0.3) or (bw_khz > 40 and prominence > 15):
        signal_type = FM_BROADCAST
        confidence = min(0.95, 0.6 + flatness * 0.3 + min(occ_bw / 500, 0.2))
    elif occ_bw < 5 and prominence > 20:
        signal_type = CARRIER
        confidence = min(0.9, 0.5 + (prominence - 20) * 0.02)
    elif 5 <= occ_bw <= 35 and flatness < 0.4:
        signal_type = NARROWBAND_FM
        confidence = 0.6 + (0.4 - flatness) * 0.5
    elif flatness > 0.5 and steepness > 2:
        signal_type = OFDM if occ_bw > 100 else TDMA
        confidence = min(0.85, 0.5 + steepness * 0.05 + flatness * 0.2)
    elif 8 <= occ_bw <= 15 and flatness > 0.3:
        signal_type = AM_BROADCAST
        confidence = 0.5

    # Temporal override: reclassify bursty signals that look like FM on airband
    if duty_cycle is not None:
        signal_type, confidence = _apply_temporal(
            signal_type, confidence, duty_cycle, power_var or 0.0,
            occ_bw, bw_khz, prominence,
        )

    peak_freq = getattr(peak, "freq_mhz", 0.0)
    band = lookup_band(peak_freq)
    band_name = band.name if band else None

    result = {
        "freq_mhz": round(peak_freq, 4),
        "power_db": round(getattr(peak, "power_db", 0.0), 1),
        "prominence_db": round(prominence, 1),
        "bandwidth_khz": round(bw_khz, 1),
        "signal_type": signal_type,
        "confidence": round(confidence, 2),
        "band": band_name,
        "transient": getattr(peak, "transient", False),
    }
    if duty_cycle is not None:
        result["duty_cycle"] = round(duty_cycle, 2)
    return result


def classify_peaks(
    freqs_mhz: np.ndarray,
    power_db: np.ndarray,
    peaks,
    waterfall_db: np.ndarray | None = None,
) -> list[dict]:
    """Classify a list of peaks and return dicts with signal_type + confidence.

    waterfall_db: optional 2D array [freq x time] in dB for temporal features.
    """
    if len(freqs_mhz) < 4 or not peaks:
        return []

    return [
        _classify_one(freqs_mhz, power_db, pk, waterfall_db)
        for i, pk in enumerate(peaks)
    ]
