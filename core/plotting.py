"""Plotting utilities for spectrum and waterfall visualization."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import numpy as np

from core.dsp import SpectrumResult, WaterfallResult


# Predefined frequency bands for sweep scanning
BANDS = {
    "fm":      {"name": "FM Radio",              "freq": 98e6,    "rate": 2.048e6},
    "air":     {"name": "Airband (lotnicze)",     "freq": 127e6,   "rate": 2.048e6},
    "433":     {"name": "433 MHz (piloty/IoT)",   "freq": 433.9e6, "rate": 2.048e6},
    "pmr":     {"name": "PMR446 (walkie-talkie)", "freq": 446.1e6, "rate": 1e6},
    "868":     {"name": "868 MHz (LoRa/IoT)",     "freq": 868e6,   "rate": 2.048e6},
    "gsm900":  {"name": "GSM 900 downlink",       "freq": 947e6,   "rate": 2.048e6},
    "adsb":    {"name": "ADS-B (samoloty)",       "freq": 1090e6,  "rate": 2.048e6},
}


def plot_spectrum(
    result: SpectrumResult,
    title: Optional[str] = None,
    save_path: Optional[str | Path] = None,
    show: bool = True,
) -> plt.Figure:
    """Plot a single PSD spectrum."""
    fig, ax = plt.subplots(figsize=(14, 4))

    ax.plot(result.freqs_mhz, result.power_db, linewidth=0.5, color="navy")
    ax.fill_between(
        result.freqs_mhz, result.power_db.min(), result.power_db, alpha=0.2, color="steelblue"
    )
    ax.set_xlabel("Częstotliwość [MHz]")
    ax.set_ylabel("Moc [dB]")
    ax.set_title(title or f"Widmo RF: {result.center_freq_mhz:.1f} MHz")
    ax.grid(True, alpha=0.3)
    ax.set_xlim(result.freqs_mhz[0], result.freqs_mhz[-1])

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150)
    if show:
        plt.show()
    return fig


def plot_waterfall(
    result: WaterfallResult,
    title: Optional[str] = None,
    save_path: Optional[str | Path] = None,
    show: bool = True,
) -> plt.Figure:
    """Plot waterfall with PSD panel on top."""
    fig, (ax_psd, ax_wf) = plt.subplots(
        2, 1,
        figsize=(14, 8),
        gridspec_kw={"height_ratios": [1, 3]},
        sharex=True,
    )

    # Top: averaged PSD
    ax_psd.plot(result.freqs_mhz, result.mean_psd_db, linewidth=0.8, color="navy")
    ax_psd.fill_between(
        result.freqs_mhz,
        result.mean_psd_db.min(),
        result.mean_psd_db,
        alpha=0.3,
        color="steelblue",
    )
    ax_psd.set_ylabel("Moc [dB]")
    ax_psd.set_title(
        title or f"RFSentinel — {result.center_freq_mhz:.1f} MHz", fontsize=13, fontweight="bold"
    )
    ax_psd.grid(True, alpha=0.3)

    # Bottom: waterfall
    vmin = np.percentile(result.power_db, 5)
    vmax = np.percentile(result.power_db, 99)
    im = ax_wf.pcolormesh(
        result.freqs_mhz,
        result.times,
        result.power_db.T,
        shading="auto",
        cmap="viridis",
        norm=Normalize(vmin=vmin, vmax=vmax),
    )
    ax_wf.set_ylabel("Czas [s]")
    ax_wf.set_xlabel("Częstotliwość [MHz]")
    fig.colorbar(im, ax=ax_wf, label="Moc [dB]", pad=0.01)

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150)
    if show:
        plt.show()
    return fig
