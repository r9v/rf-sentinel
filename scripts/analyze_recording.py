"""Offline IQ recording analyzer.

Usage:
    python scripts/analyze_recording.py <file.cf32> [--sr RATE] [--freq MHZ]
    python scripts/analyze_recording.py <directory>    (batch mode)

Reads CF32/NPZ IQ files and produces a full signal characterization:
  - Spectrum: peaks, bandwidth (-6/-20dB, occupied), spectral flatness
  - Envelope: CV, PAPR (constant envelope = FM, high PAPR = OFDM)
  - FM demod: deviation (RMS, peak, 99th pctile), inst freq distribution
  - Audio spectrum: voice band energy, modem tone detection
  - CTCSS: sub-audio squelch tone detection
  - Temporal: duty cycle, PTT bursts, power stability
  - Classification: verdict from measured characteristics
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np
from scipy.signal import welch, butter, sosfilt, find_peaks as scipy_find_peaks

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CTCSS_TONES = [
    67.0, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5, 94.8,
    97.4, 100.0, 103.5, 107.2, 110.9, 114.8, 118.8, 123.0, 127.3,
    131.8, 136.5, 141.3, 146.2, 151.4, 156.7, 162.2, 167.9, 173.8,
    179.9, 186.2, 192.8, 203.5, 210.7, 218.1, 225.7, 233.6, 241.8, 250.3,
]

ML_SAMPLE_RATE = 1.024e6


def parse_filename(path: Path) -> tuple[float | None, float | None]:
    m = re.search(r"([\d.]+)MHz(?:_([\d.]+)kHz)?", path.stem)
    if not m:
        return None, None
    freq = float(m.group(1))
    bw = float(m.group(2)) if m.group(2) else None
    return freq, bw


def lookup_db(filename: str) -> dict | None:
    db_path = ROOT / "data" / "rfsentinel.db"
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT * FROM recordings WHERE filename = ?", (filename,)
    ).fetchone()
    if not row:
        return None
    cols = [d[0] for d in conn.execute("SELECT * FROM recordings LIMIT 0").description]
    return dict(zip(cols, row))


def _measure_bw(power_db: np.ndarray, peak_idx: int, drop_db: float,
                freq_step_khz: float) -> float:
    threshold = power_db[peak_idx] - drop_db
    left = peak_idx
    while left > 0 and power_db[left] > threshold:
        left -= 1
    right = peak_idx
    while right < len(power_db) - 1 and power_db[right] > threshold:
        right += 1
    return (right - left) * freq_step_khz


def measure_dc_signal(iq: np.ndarray, fs: float, fc_mhz: float,
                      verbose: bool = True) -> dict:
    """Measure signal at DC for a VFO-centered recording."""
    nperseg = min(4096, len(iq))
    freqs, psd = welch(iq, fs=fs, nperseg=nperseg, return_onesided=False)
    freqs = np.fft.fftshift(freqs)
    psd = np.fft.fftshift(psd)
    power_db = 10 * np.log10(psd + 1e-12)

    noise_floor = float(np.median(power_db))
    freq_step_khz = float(freqs[1] - freqs[0]) / 1e3

    n = len(power_db)
    q = n // 4
    peak_idx = q + int(np.argmax(power_db[q:n - q]))
    peak_power = float(power_db[peak_idx])
    snr = peak_power - noise_floor

    bw_6db = _measure_bw(power_db, peak_idx, 6, freq_step_khz)
    bw_20db = _measure_bw(power_db, peak_idx, 20, freq_step_khz)

    sl = 10.0 ** (power_db / 10.0)
    noise_lin = 10.0 ** (noise_floor / 10.0)
    sig_power = np.maximum(sl - noise_lin, 0)
    total = np.sum(sig_power)
    if total > 0:
        cs = np.cumsum(sig_power)
        occ_lo = np.searchsorted(cs, total * 0.005)
        occ_hi = np.searchsorted(cs, total * 0.995)
        occ_bw = (occ_hi - occ_lo) * freq_step_khz
    else:
        occ_lo, occ_hi = 0, n - 1
        occ_bw = 0.0

    sl_occ = sl[occ_lo:occ_hi + 1]
    p = sl_occ[sl_occ > 0]
    flatness = float(np.exp(np.mean(np.log(p))) / np.mean(p)) if len(p) > 1 else 0.0

    if verbose:
        print("--- Spectrum (DC-centered) ---")
        print(f"  Noise floor:  {noise_floor:.1f} dB")
        print(f"  Peak power:   {peak_power:.1f} dB")
        print(f"  SNR:          {snr:.1f} dB")
        print(f"  BW -6dB:      {bw_6db:.1f} kHz")
        print(f"  BW -20dB:     {bw_20db:.1f} kHz")
        print(f"  Occupied:     {occ_bw:.1f} kHz")
        print(f"  Flatness:     {flatness:.3f}")

    return {
        "freq_mhz": round(fc_mhz, 4),
        "power_db": round(peak_power, 1),
        "snr_db": round(snr, 1),
        "prominence_db": round(snr, 1),
        "bw_6db_khz": round(bw_6db, 1),
        "bw_20db_khz": round(bw_20db, 1),
        "occ_bw_khz": round(occ_bw, 1),
        "flatness": round(flatness, 3),
    }


def analyze_envelope(iq: np.ndarray) -> dict:
    amp = np.abs(iq)
    mean_amp = float(np.mean(amp))
    std_amp = float(np.std(amp))
    cv = std_amp / mean_amp if mean_amp > 1e-12 else 0.0

    power = amp ** 2
    mean_power = float(np.mean(power))
    peak_power = float(np.max(power))
    papr = 10 * np.log10(peak_power / mean_power) if mean_power > 1e-12 else 0.0

    print("\n--- Envelope ---")
    print(f"  Amplitude CV: {cv:.3f}", end="")
    if cv < 0.15:
        print("  (constant envelope -- FM/FSK)")
    elif cv < 0.3:
        print("  (moderate variation -- FM with noise)")
    elif cv < 0.55:
        print("  (high variation -- AM/QAM/mixed)")
    else:
        print("  (noise-like -- Rayleigh ~0.52)")
    print(f"  PAPR:         {papr:.1f} dB", end="")
    if papr < 4:
        print("  (constant envelope)")
    elif papr < 8:
        print("  (moderate -- voice AM, bursty)")
    else:
        print("  (high -- OFDM, pulsed, or noise)")

    return {"cv": round(cv, 3), "papr_db": round(papr, 1)}


def isolate_signal(iq: np.ndarray, fs: float, fc_mhz: float,
                   sig_freq_mhz: float, sig_bw_khz: float) -> tuple[np.ndarray, float]:
    offset_hz = (sig_freq_mhz - fc_mhz) * 1e6
    t = np.arange(len(iq)) / fs
    shifted = iq * np.exp(-1j * 2 * np.pi * offset_hz * t)

    cutoff = max(sig_bw_khz * 1e3, 15e3)
    decim = max(1, int(fs // (cutoff * 4)))
    new_fs = fs / decim

    try:
        sos = butter(5, cutoff, btype="low", fs=fs, output="sos")
        filtered = sosfilt(sos, shifted)
    except ValueError:
        filtered = shifted
        decim = 1
        new_fs = fs

    return filtered[::decim], new_fs


def analyze_fm(iq: np.ndarray, fs: float) -> tuple[np.ndarray | None, float, dict]:
    product = iq[1:] * np.conj(iq[:-1])
    inst_freq = np.angle(product) * fs / (2 * np.pi)

    rms_dev = float(np.std(inst_freq))
    peak_dev = float(np.max(np.abs(inst_freq)))
    p99_dev = float(np.percentile(np.abs(inst_freq), 99))
    median_dev = float(np.median(np.abs(inst_freq)))

    print("\n--- FM Demodulation ---")
    print(f"  RMS deviation:    {rms_dev:.0f} Hz ({rms_dev/1000:.1f} kHz)")
    print(f"  Median |dev|:     {median_dev:.0f} Hz")
    print(f"  99th pctile |dev|:{p99_dev:.0f} Hz ({p99_dev/1000:.1f} kHz)")
    print(f"  Peak deviation:   {peak_dev:.0f} Hz ({peak_dev/1000:.1f} kHz)")

    if rms_dev < 500:
        mod_type = "carrier"
        print(f"  -> Unmodulated carrier or CW")
    elif rms_dev < 4000:
        mod_type = "nfm"
        print(f"  -> Narrowband FM (typ. 2.5-5 kHz max dev)")
    elif rms_dev < 15000:
        mod_type = "wfm_utility"
        print(f"  -> Wideband NFM / utility")
    else:
        mod_type = "wfm_broadcast"
        carson = 2 * (p99_dev + 15000)
        print(f"  -> Wideband FM broadcast (Carson BW ~{carson/1000:.0f} kHz)")

    return inst_freq, fs, {
        "rms_deviation_hz": rms_dev,
        "peak_deviation_hz": peak_dev,
        "p99_deviation_hz": p99_dev,
        "median_deviation_hz": median_dev,
        "mod_type": mod_type,
    }


def analyze_audio(inst_freq: np.ndarray, fs: float) -> dict:
    """Spectrum of FM-demodulated audio: voice vs data vs silence."""
    print("\n--- Audio Spectrum ---")
    nperseg = min(4096, len(inst_freq))
    f_audio, psd_audio = welch(inst_freq, fs=fs, nperseg=nperseg)
    psd_db = 10 * np.log10(psd_audio + 1e-12)

    voice_mask = (f_audio >= 300) & (f_audio <= 3400)
    sub_mask = f_audio < 300
    high_mask = f_audio > 3400

    voice_power = float(np.mean(psd_db[voice_mask])) if np.any(voice_mask) else -120
    sub_power = float(np.mean(psd_db[sub_mask])) if np.any(sub_mask) else -120
    high_power = float(np.mean(psd_db[high_mask])) if np.any(high_mask) else -120

    print(f"  Sub-audio (<300 Hz): {sub_power:.1f} dB")
    print(f"  Voice (300-3400 Hz): {voice_power:.1f} dB")
    print(f"  High (>3400 Hz):     {high_power:.1f} dB")

    # Check for modem tones (narrow spectral peaks in audio range)
    tones = []
    if np.any(voice_mask):
        voice_freqs = f_audio[voice_mask]
        voice_psd = psd_db[voice_mask]
        voice_noise = float(np.median(voice_psd))
        tone_idx, tone_props = scipy_find_peaks(voice_psd, height=voice_noise + 10, prominence=8)
        for ti in tone_idx:
            tones.append((float(voice_freqs[ti]), float(voice_psd[ti] - voice_noise)))
        if tones:
            for tf, tsnr in tones[:5]:
                print(f"  Tone: {tf:.0f} Hz  (SNR {tsnr:.1f} dB)")

    has_voice = voice_power > sub_power + 3 and voice_power > high_power
    has_tones = len(tones) > 0

    if has_tones:
        print(f"  -> Data/modem tones detected")
    elif has_voice:
        print(f"  -> Voice-like audio spectrum")
    else:
        print(f"  -> No clear audio content")

    return {
        "voice_power_db": voice_power,
        "sub_power_db": sub_power,
        "high_power_db": high_power,
        "has_voice": has_voice,
        "has_tones": has_tones,
        "tone_freqs": [t[0] for t in tones],
    }


def analyze_ctcss(inst_freq: np.ndarray, fs: float) -> list[tuple[float, float]]:
    print("\n--- CTCSS ---")
    try:
        sos = butter(4, [50, 300], btype="band", fs=fs, output="sos")
        sub_audio = sosfilt(sos, inst_freq)
    except ValueError:
        print("  (sample rate too low)")
        return []

    nperseg = min(max(8192, len(sub_audio) // 4), len(sub_audio))
    f_sub, psd_sub = welch(sub_audio, fs=fs, nperseg=nperseg)
    psd_db = 10 * np.log10(psd_sub + 1e-12)

    mask = (f_sub >= 50) & (f_sub <= 300)
    if not np.any(mask):
        print("  (no sub-audio range)")
        return []

    noise = float(np.median(psd_db[mask]))
    found = []
    for tone in CTCSS_TONES:
        idx = int(np.argmin(np.abs(f_sub - tone)))
        snr = psd_db[idx] - noise
        if snr > 8:
            found.append((tone, float(snr)))

    if found:
        for tone, snr in sorted(found, key=lambda x: -x[1]):
            print(f"  + {tone:.1f} Hz  (SNR {snr:.1f} dB)")
        strongest = sorted(found, key=lambda x: -x[1])[0]
        N = len(sub_audio)
        if N > 10000:
            win = np.blackman(N)
            spec = np.abs(np.fft.rfft(sub_audio * win))
            f_full = np.fft.rfftfreq(N, 1 / fs)
            search = (f_full >= strongest[0] - 3) & (f_full <= strongest[0] + 3)
            if np.any(search):
                exact_freq = float(f_full[search][np.argmax(spec[search])])
                print(f"  Exact tone: {exact_freq:.2f} Hz (FFT res={fs/N:.3f} Hz)")
    else:
        print("  No CTCSS tones detected")
    return found


def analyze_activity(iq: np.ndarray, fs: float) -> dict:
    print("\n--- Temporal ---")
    duration_s = len(iq) / fs

    window = max(1, int(0.05 * fs))
    n_windows = len(iq) // window
    if n_windows < 2:
        print("  (too short for temporal analysis)")
        return {"duty_cycle": 1.0, "bursts": 0, "duration_s": duration_s,
                "power_std_db": 0, "burst_lengths": []}

    chunks = iq[:n_windows * window].reshape(n_windows, window)
    power_db = 10 * np.log10(np.mean(np.abs(chunks) ** 2, axis=1) + 1e-12)
    power_std = float(np.std(power_db))

    noise_floor = float(np.percentile(power_db, 25))
    threshold = noise_floor + 3
    active = power_db > threshold
    duty = float(np.mean(active))

    transitions = np.diff(active.astype(int))
    bursts = int(np.sum(transitions == 1))

    print(f"  Duration:     {duration_s:.2f}s")
    print(f"  Mean power:   {float(np.mean(power_db)):.1f} dB")
    print(f"  Power std:    {power_std:.2f} dB", end="")
    if power_std < 0.5:
        print("  (very stable)")
    elif power_std < 2:
        print("  (stable)")
    else:
        print("  (variable)")
    print(f"  Duty cycle:   {duty:.0%}")
    print(f"  PTT bursts:   {bursts}")

    burst_lengths = []
    if bursts > 0:
        in_burst = False
        start = 0
        for i, a in enumerate(active):
            if a and not in_burst:
                start = i
                in_burst = True
            elif not a and in_burst:
                burst_lengths.append((i - start) * window / fs)
                in_burst = False
        if in_burst:
            burst_lengths.append((len(active) - start) * window / fs)
        if burst_lengths:
            print(f"  Burst lengths: {min(burst_lengths):.2f}s - {max(burst_lengths):.2f}s "
                  f"(avg {np.mean(burst_lengths):.2f}s)")

    return {
        "duty_cycle": duty, "bursts": bursts, "duration_s": duration_s,
        "power_std_db": power_std, "burst_lengths": burst_lengths,
    }


def analyze_framing(inst_freq: np.ndarray, fs: float) -> dict:
    """Frame-fold FM-demod signal at candidate periods to identify TDMA protocols."""
    print("\n--- Frame Folding ---")
    protocols = {
        "P25-P2":   0.015,
        "NXDN":     0.020,
        "DMR-slot": 0.030,
        "dPMR":     0.040,
        "TETRA":    0.05667,
        "DMR":      0.060,
    }

    sig_std = float(np.std(inst_freq))
    if sig_std < 1e-6:
        print("  (no modulation to fold)")
        return {"has_framing": False, "best_period_ms": 0, "best_score": 0,
                "protocol_scores": {}}

    test_periods = np.arange(0.005, 0.150, 0.0005)
    scores = np.zeros(len(test_periods))

    for i, period in enumerate(test_periods):
        spf = int(period * fs)
        if spf < 10:
            continue
        n_frames = len(inst_freq) // spf
        if n_frames < 5:
            continue
        folded = inst_freq[:n_frames * spf].reshape(n_frames, spf)
        mean_frame = np.mean(folded, axis=0)
        scores[i] = float(np.std(mean_frame)) / sig_std

    best_idx = int(np.argmax(scores))
    best_period = float(test_periods[best_idx])
    best_score = float(scores[best_idx])

    protocol_scores = {}
    for name, period in protocols.items():
        idx = int(np.argmin(np.abs(test_periods - period)))
        protocol_scores[name] = float(scores[idx])

    has_framing = best_score > 0.08

    if has_framing:
        print(f"  Best period: {best_period*1000:.1f} ms (score {best_score:.3f})")
        for name, score in sorted(protocol_scores.items(), key=lambda x: -x[1]):
            flag = " <<<" if score > 0.08 else ""
            print(f"    {name:10s} {protocols[name]*1000:6.1f} ms  score={score:.3f}{flag}")
    else:
        print("  No TDMA frame structure detected")

    return {
        "has_framing": has_framing,
        "best_period_ms": round(best_period * 1000, 1),
        "best_score": round(best_score, 3),
        "protocol_scores": protocol_scores,
        "periods_ms": (test_periods * 1000).tolist(),
        "scores": scores.tolist(),
    }


def generate_plots(path: Path, iq: np.ndarray, fs: float, fc_mhz: float,
                   inst_freq: np.ndarray, demod_fs: float,
                   framing: dict) -> None:
    """Generate comprehensive diagnostic plots and save as PNG next to the recording."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  (matplotlib not available, skipping plots)")
        return

    out = path.with_name(path.stem + "_analysis.png")
    fig, axes = plt.subplots(3, 2, figsize=(16, 14))

    # [0,0] Spectrogram
    ax = axes[0, 0]
    nfft = min(512, len(iq) // 4)
    ax.specgram(iq, NFFT=nfft, Fs=fs / 1e3, Fc=fc_mhz * 1e3,
                noverlap=int(nfft * 0.9), cmap="inferno")
    ax.set_title(f"{fc_mhz:.3f} MHz | Spectrogram")
    ax.set_ylabel("Freq [kHz]")
    ax.set_xlabel("Time [s]")

    # [0,1] RF PSD
    ax = axes[0, 1]
    nperseg = min(4096, len(iq))
    f_rf, psd_rf = welch(iq, fs=fs, nperseg=nperseg, return_onesided=False)
    f_rf = np.fft.fftshift(f_rf)
    psd_rf = np.fft.fftshift(psd_rf)
    ax.plot(f_rf / 1e3, 10 * np.log10(psd_rf + 1e-20), color="#00d4ff", linewidth=0.5)
    ax.set_title("RF Power Spectral Density")
    ax.set_xlabel("Offset [kHz]")
    ax.set_ylabel("PSD [dB]")
    ax.grid(True, alpha=0.3)

    # [1,0] FM demod time series
    ax = axes[1, 0]
    t = np.arange(len(inst_freq)) / demod_fs
    ax.plot(t, inst_freq / 1e3, linewidth=0.3, color="#00d4ff")
    ax.set_title("FM Demod | Inst. Frequency Deviation")
    ax.set_ylabel("Deviation [kHz]")
    ax.set_xlabel("Time [s]")
    ax.grid(True, alpha=0.3)

    # [1,1] Audio spectrum
    ax = axes[1, 1]
    nperseg_a = min(4096, len(inst_freq))
    f_a, psd_a = welch(inst_freq, fs=demod_fs, nperseg=nperseg_a)
    ax.semilogy(f_a, psd_a, color="#00d4ff", linewidth=0.5)
    ax.axvspan(300, 3000, alpha=0.08, color="green", label="Voice band")
    for ct in CTCSS_TONES:
        if ct < demod_fs / 2:
            ax.axvline(ct, color="gray", linestyle=":", alpha=0.15, linewidth=0.5)
    ax.set_title("FM Demod Audio Spectrum")
    ax.set_xlabel("Frequency [Hz]")
    ax.set_ylabel("PSD")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    # [2,0] Frame folding scores OR CTCSS high-res
    ax = axes[2, 0]
    if framing.get("has_framing") and framing.get("scores"):
        periods = framing["periods_ms"]
        sc = framing["scores"]
        ax.plot(periods, sc, color="#00d4ff", linewidth=0.8)
        ax.axhline(0.08, color="red", linestyle=":", alpha=0.5, label="Threshold")
        best_ms = framing["best_period_ms"]
        ax.axvline(best_ms, color="lime", linestyle="--", alpha=0.8,
                   label=f"Best: {best_ms:.1f} ms")
        for name, period_ms in [("DMR", 60), ("NXDN", 20), ("TETRA", 56.7),
                                ("dPMR", 40), ("P25", 15)]:
            ax.axvline(period_ms, color="orange", linestyle=":", alpha=0.3)
            ax.text(period_ms, max(sc) * 0.95, name, fontsize=7, ha="center", color="orange")
        ax.set_title("Frame Folding Scores")
        ax.set_xlabel("Period [ms]")
        ax.set_ylabel("Fold Score")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
    else:
        N = len(inst_freq)
        if N > 1000:
            try:
                sos = butter(4, [50, 300], btype="band", fs=demod_fs, output="sos")
                sub = sosfilt(sos, inst_freq)
            except ValueError:
                sub = inst_freq
            win = np.blackman(len(sub))
            spec = np.abs(np.fft.rfft(sub * win))
            freqs_hr = np.fft.rfftfreq(len(sub), 1 / demod_fs)
            mag_hr = 20 * np.log10(spec + 1e-20)
            mask_hr = (freqs_hr >= 50) & (freqs_hr <= 300)
            if np.any(mask_hr):
                ax.plot(freqs_hr[mask_hr], mag_hr[mask_hr], color="#00d4ff", linewidth=0.5)
                for ct in CTCSS_TONES:
                    if 50 <= ct <= 300:
                        ax.axvline(ct, color="gray", linestyle=":", alpha=0.2, linewidth=0.5)
                ax.set_title(f"CTCSS High-Res (res={demod_fs/len(sub):.3f} Hz)")
                ax.set_xlabel("Frequency [Hz]")
                ax.set_ylabel("Magnitude [dB]")
                ax.grid(True, alpha=0.3)

    # [2,1] Sub-audio vs voice power over time
    ax = axes[2, 1]
    chunk = max(1, int(0.25 * demod_fs))
    n_chunks = max(1, len(inst_freq) // chunk)
    if n_chunks > 2 and demod_fs > 600:
        try:
            sos_tone = butter(4, [60, 200], btype="band", fs=demod_fs, output="sos")
            voice_hi = min(3000, demod_fs / 2 - 1)
            sos_voice = butter(4, [300, voice_hi], btype="band", fs=demod_fs, output="sos")
            tone_filt = sosfilt(sos_tone, inst_freq)
            voice_filt = sosfilt(sos_voice, inst_freq)
            t_c = np.arange(n_chunks) * chunk / demod_fs
            tone_pwr = [10 * np.log10(np.mean(tone_filt[i * chunk:(i + 1) * chunk] ** 2) + 1e-20)
                        for i in range(n_chunks)]
            voice_pwr = [10 * np.log10(np.mean(voice_filt[i * chunk:(i + 1) * chunk] ** 2) + 1e-20)
                         for i in range(n_chunks)]
            ax.plot(t_c, tone_pwr, color="red", linewidth=1, label="Sub-audio (60-200 Hz)")
            ax.plot(t_c, voice_pwr, color="lime", linewidth=1, label="Voice (300-3k Hz)")
            ax.set_title("Sub-Audio vs Voice Power Over Time")
            ax.set_xlabel("Time [s]")
            ax.set_ylabel("Power [dB]")
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3)
        except ValueError:
            ax.text(0.5, 0.5, "Filter error", transform=ax.transAxes, ha="center")
    else:
        ax.text(0.5, 0.5, "Too short for time analysis", transform=ax.transAxes, ha="center")

    plt.tight_layout()
    plt.savefig(str(out), dpi=120, bbox_inches="tight")
    plt.close()
    print(f"\n  Plots saved: {out}")


def analyze_snippet(iq: np.ndarray, fs: float, verbose: bool = True) -> str:
    """Classify a short pre-centered ML snippet (typically 1024 samples).

    These snippets are already frequency-shifted so the detected signal is at DC,
    and power-normalized. Classification is purely from measured signal characteristics.
    """
    n = len(iq)

    amp = np.abs(iq)
    cv = float(np.std(amp)) / float(np.mean(amp) + 1e-12)
    power = amp ** 2
    papr = 10 * np.log10(float(np.max(power)) / float(np.mean(power) + 1e-12))

    X = np.fft.fftshift(np.fft.fft(iq, n=n))
    mag = np.abs(X) ** 2
    total_power = float(np.sum(mag))
    if total_power > 0:
        cs = np.cumsum(mag)
        occ_lo = np.searchsorted(cs, total_power * 0.005)
        occ_hi = np.searchsorted(cs, total_power * 0.995)
        occ_bw_frac = (occ_hi - occ_lo) / n
        occ_bw_khz = occ_bw_frac * fs / 1e3
    else:
        occ_bw_frac = 1.0
        occ_bw_khz = fs / 1e3

    p = mag[mag > 0]
    flatness = float(np.exp(np.mean(np.log(p))) / np.mean(p)) if len(p) > 1 else 0.0

    center_bins = int(200e3 / fs * n)
    mid = n // 2
    lo = max(0, mid - center_bins // 2)
    hi = min(n, mid + center_bins // 2)
    center_mag = mag[lo:hi]
    cp = center_mag[center_mag > 0]
    center_flatness = float(np.exp(np.mean(np.log(cp))) / np.mean(cp)) if len(cp) > 1 else 0.0

    if verbose:
        print("\n--- Snippet Analysis ---")
        print(f"  Envelope CV:      {cv:.3f}", end="")
        if cv < 0.15:
            print("  (constant envelope)")
        elif cv < 0.35:
            print("  (moderate variation)")
        else:
            print("  (high variation)")
        print(f"  PAPR:             {papr:.1f} dB", end="")
        if papr < 4:
            print("  (constant envelope)")
        elif papr < 8:
            print("  (moderate)")
        else:
            print("  (high -- OFDM/pulsed/noise)")
        print(f"  Occupied BW:      {occ_bw_khz:.0f} kHz ({occ_bw_frac:.0%} of capture)")
        print(f"  Spectral flatness:{flatness:.3f} (full), {center_flatness:.3f} (center 200k)")

    # Constant envelope → FM-like
    if cv < 0.2 and papr < 5:
        label = "Constant-envelope (FM-like)"
    # High CV + wide + flat → multi-carrier
    elif cv > 0.3 and occ_bw_frac > 0.3 and flatness > 0.3:
        label = "OFDM / multi-carrier"
    # High CV + high PAPR → bursty digital
    elif cv > 0.35 and papr > 5:
        label = "Digital (bursty)" if center_flatness > 0.3 else "Digital (structured)"
    # Moderate CV, low PAPR → likely FM with noise
    elif cv < 0.3:
        label = "FM-like (moderate envelope)"
    # Moderate-high CV, low flatness → narrowband or AM-like
    elif flatness < 0.3:
        label = "Narrowband (non-constant envelope)"
    else:
        label = "Unknown"

    if verbose:
        print(f"\n--- Verdict ---")
        print(f"  >> {label}")
    return label


def classify_signal(signal: dict, envelope: dict, fm: dict, audio: dict,
                    ctcss: list, activity: dict,
                    framing: dict | None = None) -> str:
    bw = signal["occ_bw_khz"]
    flatness = signal["flatness"]
    cv = envelope["cv"]
    papr = envelope["papr_db"]
    deviation = fm["rms_deviation_hz"]
    mod = fm["mod_type"]
    duty = activity["duty_cycle"]
    has_ctcss = len(ctcss) > 0
    has_voice = audio.get("has_voice", False)
    has_tones = audio.get("has_tones", False)

    if cv > 0.48 and signal["snr_db"] < 10:
        return "Noise (no signal)"

    # FM broadcast: high deviation with constant envelope
    if mod == "wfm_broadcast":
        return "FM broadcast"
    if deviation > 15000 and cv < 0.3:
        return "FM broadcast"

    # NFM with CTCSS (1-3 tones = real, many = broadband sub-audio false positive)
    if has_ctcss and len(ctcss) <= 3:
        tone_str = f" (CTCSS {ctcss[0][0]:.1f} Hz)"
        stable = activity["power_std_db"] < 1.0
        if duty > 0.8 or (stable and activity["bursts"] == 0):
            return f"NFM repeater{tone_str}"
        return f"NFM voice{tone_str}"

    # TDMA framing → digital protocol
    if framing and framing.get("has_framing"):
        ps = framing.get("protocol_scores", {})
        best_ms = framing["best_period_ms"]
        if ps.get("DMR", 0) > 0.08 or ps.get("DMR-slot", 0) > 0.08:
            return "DMR"
        if ps.get("NXDN", 0) > 0.08:
            return "NXDN"
        if ps.get("TETRA", 0) > 0.08:
            return "TETRA"
        if ps.get("dPMR", 0) > 0.08:
            return "dPMR"
        if ps.get("P25-P2", 0) > 0.08:
            return "P25 Phase 2"
        return f"Digital (framed, {best_ms:.0f}ms)"

    # High envelope variation → not constant-envelope → not FM
    # FM-demod of non-FM signals gives fake deviation, so skip FM checks here
    if cv > 0.35 and papr > 8:
        if flatness > 0.4 and bw > 50:
            return "OFDM / multi-carrier"
        if flatness > 0.4:
            return "Digital (wideband flat)"
        return "Digital (structured)"

    # CW carrier / beacon
    if mod == "carrier":
        if activity["power_std_db"] < 0.5:
            return "CW carrier / beacon"
        return "Carrier (unmodulated)"

    # NFM (envelope consistent with FM)
    if mod == "nfm":
        if has_voice and duty < 0.5 and activity["bursts"] > 0:
            return "NFM voice (PTT)"
        if has_voice:
            return "NFM voice"
        if has_tones:
            return "NFM data/signaling"
        if duty < 0.5 and activity["bursts"] > 0:
            return "NFM (bursty)"
        return "NFM"

    if mod == "wfm_utility":
        if has_tones:
            return "NFM data link"
        return "NFM utility"

    # AM-like: high envelope variation, voice band, low FM deviation
    if cv > 0.25 and has_voice and deviation < 5000:
        return "AM voice"

    if bw > 150:
        return "Wideband (unknown)"
    if bw > 20:
        return "Narrowband (unknown)"
    return "Unknown"


def load_file(path: Path, sr_override: float | None = None,
              freq_override: float | None = None) -> tuple[np.ndarray, float | None, float | None]:
    if path.suffix == ".npz":
        d = np.load(str(path), allow_pickle=False)
        iq = d["iq"].astype(np.complex64)
        fc_mhz = float(d["freq_mhz"]) if "freq_mhz" in d else 0.0
        fs = sr_override or ML_SAMPLE_RATE
        if freq_override:
            fc_mhz = freq_override
        return iq, fs, fc_mhz

    iq = np.fromfile(str(path), dtype=np.complex64)
    fn_freq, fn_bw = parse_filename(path)
    meta = lookup_db(path.name)

    fs = sr_override or (meta and meta.get("sample_rate")) or (fn_bw and fn_bw * 1000) or None
    fc_mhz = freq_override or (meta and meta.get("freq_mhz")) or fn_freq or None
    return iq, fs, fc_mhz


def analyze_one(path: Path, fs: float, fc_mhz: float, iq: np.ndarray,
                verbose: bool = True, plot: bool = False) -> str | None:
    duration_s = len(iq) / fs
    short = len(iq) < 4096

    if verbose:
        print(f"=== {path.name} ===")
        print(f"  Center:      {fc_mhz:.4f} MHz")
        print(f"  Sample rate: {fs:,.0f} Hz")
        print(f"  Samples:     {len(iq):,}")
        if duration_s < 1:
            print(f"  Duration:    {duration_s*1000:.1f} ms")
        else:
            print(f"  Duration:    {duration_s:.2f} s")
        print(f"  File size:   {path.stat().st_size:,} bytes")

    if short:
        return analyze_snippet(iq, fs, verbose=verbose)

    signal = measure_dc_signal(iq, fs, fc_mhz, verbose=verbose)

    if signal["snr_db"] < 3:
        if verbose:
            print("\n  >> Noise (no signal)")
        return "Noise (no signal)"

    sig_iq, sig_fs = isolate_signal(
        iq, fs, fc_mhz, fc_mhz, max(signal["bw_20db_khz"], 10),
    )
    if verbose:
        print(f"\n  (decimated {fs/1e3:.0f} -> {sig_fs/1e3:.0f} kHz)")
    envelope = analyze_envelope(sig_iq)

    inst_freq, demod_fs, fm = analyze_fm(sig_iq, sig_fs)

    audio = analyze_audio(inst_freq, demod_fs)
    ctcss = analyze_ctcss(inst_freq, demod_fs)
    activity = analyze_activity(iq, fs)
    framing = analyze_framing(inst_freq, demod_fs)

    classification = classify_signal(signal, envelope, fm, audio, ctcss, activity, framing)
    if verbose:
        print(f"\n--- Verdict ---")
        print(f"  >> {classification}")

    if plot:
        generate_plots(path, iq, fs, fc_mhz, inst_freq, demod_fs, framing)

    return classification


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze IQ recording (.cf32 / .npz)")
    parser.add_argument("file", help="Path to IQ file or directory")
    parser.add_argument("--sr", type=float, help="Sample rate (Hz)")
    parser.add_argument("--freq", type=float, help="Center frequency (MHz)")
    parser.add_argument("--plot", action="store_true", help="Generate diagnostic plots")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"Not found: {path}")
        sys.exit(1)

    if path.is_dir():
        files = sorted(path.glob("*.cf32")) + sorted(path.glob("*.npz"))
        if not files:
            print(f"No .cf32 or .npz files in {path}")
            sys.exit(1)
        print(f"Batch: {len(files)} files in {path.name}/\n")

        results = {}
        for f in files:
            iq, fs, fc_mhz = load_file(f, args.sr, args.freq)
            if fs is None or fc_mhz is None:
                continue
            classification = analyze_one(f, fs, fc_mhz, iq, verbose=False)
            freq_str = f"{fc_mhz:.2f}"
            results.setdefault(freq_str, []).append((f.name, classification))

        print("\n--- Summary by frequency ---")
        for freq, items in sorted(results.items(), key=lambda x: float(x[0])):
            classes = {}
            for name, cls in items:
                cls = cls or "no signal"
                classes[cls] = classes.get(cls, 0) + 1
            counts = ", ".join(f"{c} x{n}" for c, n in sorted(classes.items(), key=lambda x: -x[1]))
            print(f"  {freq} MHz ({len(items)} files): {counts}")
        return

    iq, fs, fc_mhz = load_file(path, args.sr, args.freq)
    if fs is None:
        print("Cannot determine sample rate. Use --sr")
        sys.exit(1)
    if fc_mhz is None:
        print("Cannot determine center frequency. Use --freq")
        sys.exit(1)

    analyze_one(path, fs, fc_mhz, iq, plot=args.plot)


if __name__ == "__main__":
    main()
