"""RFSentinel CLI — command-line interface."""

from __future__ import annotations

import argparse
import sys


def cmd_scan(args: argparse.Namespace) -> None:
    """Single-band PSD scan."""
    from core.sdr import SDRDevice, CaptureConfig
    from core.dsp import compute_psd
    from core.plotting import plot_spectrum

    config = CaptureConfig(
        center_freq=args.freq * 1e6,
        sample_rate=args.rate * 1e6,
        duration=args.duration,
        gain=args.gain,
    )

    print(f"Skanowanie {args.freq} MHz ({args.duration}s)...")
    with SDRDevice() as sdr:
        capture = sdr.capture(config)

    result = compute_psd(capture)
    save = f"scan_{args.freq}MHz.png" if args.save else None
    plot_spectrum(result, save_path=save)
    if save:
        print(f"Zapisano: {save}")


def cmd_waterfall(args: argparse.Namespace) -> None:
    """Waterfall / spectrogram display."""
    from core.sdr import SDRDevice, CaptureConfig
    from core.dsp import compute_waterfall
    from core.plotting import plot_waterfall

    config = CaptureConfig(
        center_freq=args.freq * 1e6,
        sample_rate=args.rate * 1e6,
        duration=args.duration,
        gain=args.gain,
    )

    print(f"Waterfall {args.freq} MHz ({args.duration}s)...")
    with SDRDevice() as sdr:
        capture = sdr.capture(config)

    result = compute_waterfall(capture)
    save = f"waterfall_{args.freq}MHz.png" if args.save else None
    plot_waterfall(result, save_path=save)
    if save:
        print(f"Zapisano: {save}")


def cmd_sweep(args: argparse.Namespace) -> None:
    """Multi-band sweep scan."""
    from core.sdr import SDRDevice, CaptureConfig
    from core.dsp import compute_psd
    from core.plotting import BANDS, plot_spectrum

    import matplotlib.pyplot as plt

    bands = list(BANDS.values())
    fig, axes = plt.subplots(len(bands), 1, figsize=(14, 3 * len(bands)))

    with SDRDevice() as sdr:
        for i, band in enumerate(bands):
            print(f"Skanowanie: {band['name']}...")
            config = CaptureConfig(
                center_freq=band["freq"],
                sample_rate=band["rate"],
                gain=args.gain,
                duration=1.0,
            )
            capture = sdr.capture(config)
            result = compute_psd(capture)

            axes[i].plot(result.freqs_mhz, result.power_db, linewidth=0.5, color="navy")
            axes[i].set_title(band["name"], fontsize=11, fontweight="bold")
            axes[i].set_ylabel("dB")
            axes[i].grid(True, alpha=0.3)
            axes[i].set_xlim(result.freqs_mhz[0], result.freqs_mhz[-1])

    axes[-1].set_xlabel("Częstotliwość [MHz]")
    plt.tight_layout()

    if args.save:
        fig.savefig("sweep_bands.png", dpi=150)
        print("Zapisano: sweep_bands.png")
    plt.show()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="rfsentinel",
        description="RFSentinel — RF spectrum monitoring & classification",
    )
    parser.add_argument("--gain", type=float, default=30.0, help="SDR gain [dB]")
    parser.add_argument("--save", action="store_true", help="Save plot to PNG")

    sub = parser.add_subparsers(dest="command", required=True)

    # scan
    p_scan = sub.add_parser("scan", help="Single-band PSD scan")
    p_scan.add_argument("--freq", type=float, default=98.0, help="Center freq [MHz]")
    p_scan.add_argument("--duration", type=float, default=5.0, help="Duration [s]")
    p_scan.add_argument("--rate", type=float, default=1.024, help="Sample rate [Msps]")

    # waterfall
    p_wf = sub.add_parser("waterfall", help="Waterfall spectrogram")
    p_wf.add_argument("--freq", type=float, default=98.0, help="Center freq [MHz]")
    p_wf.add_argument("--duration", type=float, default=5.0, help="Duration [s]")
    p_wf.add_argument("--rate", type=float, default=1.024, help="Sample rate [Msps]")

    # sweep
    p_sweep = sub.add_parser("sweep", help="Multi-band sweep")

    args = parser.parse_args()

    commands = {"scan": cmd_scan, "waterfall": cmd_waterfall, "sweep": cmd_sweep}
    commands[args.command](args)


if __name__ == "__main__":
    main()
