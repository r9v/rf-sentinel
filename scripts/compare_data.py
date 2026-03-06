"""Compare raw IQ properties between training data and live SDR captures.

Usage:
    python -m scripts.compare_data --training data/radioml.npz data/synthetic.npz \
        --live data/debug/fm data/debug/noise

    # Feature-level similarity (per-channel cosine similarity matrix):
    python -m scripts.compare_data --features --training data/radioml.npz data/synthetic.npz \
        --live data/debug/fm data/debug/noise
"""

from __future__ import annotations

import argparse
import glob
import os

import numpy as np
from numpy.linalg import norm

from core.ml.features import N_CHANNELS, N_IQ, iq_to_channels
from core.ml.model import ML_CLASSES, N_CLASSES


def iq_metrics(iq: np.ndarray) -> dict:
    """Compute raw IQ diagnostic metrics for a single 1024-sample snippet."""
    iq = iq.astype(np.complex128)
    n = len(iq)

    power = np.mean(np.abs(iq) ** 2)
    amp = np.abs(iq)

    S = np.abs(np.fft.fftshift(np.fft.fft(iq))) ** 2
    S_db = 10 * np.log10(np.maximum(S, 1e-30))
    peak_bin = int(np.argmax(S))

    # SNR: peak power vs median power
    median_power = np.median(S)
    snr_db = 10 * np.log10(S[peak_bin] / max(median_power, 1e-30))

    # Spectral occupancy: fraction of bins within 10 dB of peak
    threshold = S_db[peak_bin] - 10
    occupancy = np.mean(S_db > threshold)

    # Frequency offset: peak distance from center (fraction of bandwidth)
    freq_offset = abs(peak_bin - n // 2) / n

    # PAPR: Peak-to-Average Power Ratio
    papr_db = 10 * np.log10(np.max(amp ** 2) / max(power, 1e-30))

    # Noise floor flatness: std of bottom 25% of spectrum
    sorted_s = np.sort(S_db)
    noise_floor_std = np.std(sorted_s[: n // 4])

    # DC spike: ratio of DC bin power to mean
    dc_bin = n // 2
    dc_ratio = S[dc_bin] / max(np.mean(S), 1e-30)

    # IQ balance: ratio of I power to Q power (1.0 = balanced)
    i_power = np.mean(iq.real ** 2)
    q_power = np.mean(iq.imag ** 2)
    iq_balance = i_power / max(q_power, 1e-30)

    # Amplitude distribution: kurtosis (Gaussian=3, constant envelope<3)
    amp_centered = amp - amp.mean()
    amp_std = amp.std() + 1e-12
    kurtosis = np.mean((amp_centered / amp_std) ** 4)

    return {
        "snr_db": snr_db,
        "occupancy": occupancy,
        "freq_offset": freq_offset,
        "papr_db": papr_db,
        "noise_floor_std": noise_floor_std,
        "dc_ratio": dc_ratio,
        "iq_balance": iq_balance,
        "kurtosis": kurtosis,
    }


def load_training(npz_paths: list[str]) -> dict[str, list[np.ndarray]]:
    """Load training data grouped by class label."""
    per_class: dict[str, list[np.ndarray]] = {c: [] for c in ML_CLASSES}
    for path in npz_paths:
        data = np.load(path)
        iq_all = data["iq"]
        labels = data["labels"]
        for i in range(len(labels)):
            cls = ML_CLASSES[labels[i]]
            per_class[cls].append(iq_all[i])
    return per_class


def load_live(debug_dirs: list[str]) -> dict[str, list[np.ndarray]]:
    """Load live captures from data/debug/ subdirs."""
    per_class: dict[str, list[np.ndarray]] = {}
    for d in debug_dirs:
        if not os.path.isdir(d):
            continue
        class_name = os.path.basename(d).lower()
        files = sorted(glob.glob(os.path.join(d, "*.npz")))
        if not files:
            continue
        samples = []
        for f in files:
            data = np.load(f)
            samples.append(data["iq"])
        per_class[class_name] = samples
    return per_class


def summarize(samples: list[np.ndarray], max_n: int = 500) -> dict[str, tuple[float, float]]:
    """Compute mean and std of each metric across samples."""
    if not samples:
        return {}
    rng = np.random.default_rng(42)
    if len(samples) > max_n:
        idx = rng.choice(len(samples), max_n, replace=False)
        samples = [samples[i] for i in idx]

    all_metrics: dict[str, list[float]] = {}
    for s in samples:
        m = iq_metrics(s)
        for k, v in m.items():
            all_metrics.setdefault(k, []).append(v)

    return {k: (np.mean(v), np.std(v)) for k, v in all_metrics.items()}


METRIC_NAMES = ["snr_db", "occupancy", "freq_offset", "papr_db",
                "noise_floor_std", "dc_ratio", "iq_balance", "kurtosis"]
METRIC_FMT = {
    "snr_db": "{:6.1f}",
    "occupancy": "{:5.1%}",
    "freq_offset": "{:6.3f}",
    "papr_db": "{:6.1f}",
    "noise_floor_std": "{:6.2f}",
    "dc_ratio": "{:6.1f}",
    "iq_balance": "{:6.3f}",
    "kurtosis": "{:6.2f}",
}


def print_comparison(training: dict[str, list[np.ndarray]], live: dict[str, list[np.ndarray]]):
    live_classes = sorted(live.keys())
    if not live_classes:
        print("No live captures found.")
        return

    for cls in live_classes:
        print(f"\n{'='*72}")
        print(f"  CLASS: {cls}")
        print(f"{'='*72}")

        live_summary = summarize(live[cls])
        train_summary = summarize(training.get(cls, []))

        # Map debug dir names to training class names
        if not train_summary:
            # Try mapping debug names to training names
            mapping = {"digital": "digital", "noise": "noise"}
            mapped = mapping.get(cls)
            if mapped and mapped in training:
                train_summary = summarize(training[mapped])

        n_live = len(live[cls])
        n_train = len(training.get(cls, []))
        print(f"  Live: {n_live} samples  |  Training: {n_train} samples")

        header = f"  {'Metric':<18s}  {'Live':>14s}  {'Training':>14s}  {'Delta':>8s}"
        print(f"\n{header}")
        print(f"  {'-'*58}")

        for m in METRIC_NAMES:
            if m not in live_summary:
                continue
            l_mean, l_std = live_summary[m]
            fmt = METRIC_FMT[m]
            live_str = f"{fmt.format(l_mean)} ±{fmt.format(l_std).strip()}"

            if m in train_summary:
                t_mean, t_std = train_summary[m]
                train_str = f"{fmt.format(t_mean)} ±{fmt.format(t_std).strip()}"
                delta = l_mean - t_mean
                delta_str = f"{delta:+.2f}"
            else:
                train_str = "  (no data)"
                delta_str = ""

            print(f"  {m:<18s}  {live_str:>14s}  {train_str:>14s}  {delta_str:>8s}")

    # Overall comparison
    print(f"\n{'='*72}")
    print("  KEY DIFFERENCES TO WATCH:")
    print(f"{'='*72}")
    print("  - snr_db:          Live signals much weaker/stronger than training?")
    print("  - occupancy:       Different spectral width = different BW assumptions")
    print("  - freq_offset:     Training centered vs live off-center")
    print("  - dc_ratio:        DC spike from SDR hardware (not in synthetic data)")
    print("  - iq_balance:      Real SDR has IQ imbalance, synthetic doesn't")
    print("  - kurtosis:        Amplitude distribution shape differences")


CH_NAMES = [
    "I", "Q", "instfreq", "amp", "ifvar", "cyclo",
    "spec1M", "spec200k", "specdelta", "spec25k",
    "acf_full", "acf_200k", "ifreq_acf", "envvar", "ifreq_hist", "papr",
]


def _compute_class_means(
    sources: dict[str, list[np.ndarray]], max_per_class: int = 200,
) -> dict[str, np.ndarray]:
    """Compute per-class mean feature vector (N_CHANNELS, N_IQ)."""
    rng = np.random.default_rng(42)
    means: dict[str, np.ndarray] = {}
    for cls, samples in sources.items():
        if not samples:
            continue
        if len(samples) > max_per_class:
            idx = rng.choice(len(samples), max_per_class, replace=False)
            samples = [samples[i] for i in idx]
        feats = np.stack([iq_to_channels(s) for s in samples])
        means[cls] = feats.mean(axis=0)
        print(f"    {cls}: {len(samples)} samples → features computed")
    return means


def print_feature_similarity(
    training: dict[str, list[np.ndarray]],
    live: dict[str, list[np.ndarray]],
):
    print("\nComputing training class means...")
    train_means = _compute_class_means(training)
    live_means: dict[str, np.ndarray] = {}
    if live:
        print("Computing live class means...")
        live_means = _compute_class_means(live)

    all_means = train_means

    classes = [c for c in ML_CLASSES if c in all_means]
    if len(classes) < 2:
        print("Need at least 2 classes for similarity comparison.")
        return

    print(f"\n{'='*72}")
    print("  PAIRWISE COSINE SIMILARITY (all channels, higher = more confused)")
    print(f"{'='*72}")
    header = "        " + "  ".join(f"{c:>6s}" for c in classes)
    print(header)
    for a in classes:
        row = f"  {a:>5s} "
        for b in classes:
            if b == a:
                row += "     - "
            else:
                va = all_means[a].flatten()
                vb = all_means[b].flatten()
                cos = np.dot(va, vb) / (norm(va) * norm(vb) + 1e-12)
                marker = "*" if cos > 0.95 else " "
                row += f" {cos:.3f}{marker}"
        print(row)

    print(f"\n{'='*72}")
    print("  PER-CHANNEL SIMILARITY (worst training pairs, >0.90 marked <<<)")
    print(f"{'='*72}")
    pairs = []
    for i, a in enumerate(classes):
        for b in classes[i + 1:]:
            va = all_means[a].flatten()
            vb = all_means[b].flatten()
            cos = np.dot(va, vb) / (norm(va) * norm(vb) + 1e-12)
            pairs.append((cos, a, b))
    pairs.sort(reverse=True)

    for overall_cos, a, b in pairs[:6]:
        print(f"\n  {a} vs {b} (overall: {overall_cos:.4f}):")
        for ch in range(N_CHANNELS):
            va = all_means[a][ch]
            vb = all_means[b][ch]
            cos = np.dot(va, vb) / (norm(va) * norm(vb) + 1e-12)
            marker = " <<<" if cos > 0.90 else ""
            print(f"    {CH_NAMES[ch]:>10s} (ch{ch:2d}): {cos:.4f}{marker}")

    if live_means:
        print(f"\n{'='*72}")
        print("  LIVE vs TRAINING (same-class cosine similarity)")
        print(f"{'='*72}")
        for cls in sorted(live_means.keys()):
            if cls not in train_means:
                print(f"  {cls}: no training data")
                continue
            for ch in range(N_CHANNELS):
                va = live_means[cls][ch]
                vb = train_means[cls][ch]
                cos = np.dot(va, vb) / (norm(va) * norm(vb) + 1e-12)
                if ch == 0:
                    print(f"\n  {cls}:")
                gap = " !!!" if cos < 0.5 else ""
                print(f"    {CH_NAMES[ch]:>10s}: {cos:.4f}{gap}")


def main():
    parser = argparse.ArgumentParser(description="Compare training vs live IQ data")
    parser.add_argument("--training", nargs="*", default=[], help="Training .npz files")
    parser.add_argument("--live", nargs="+", required=True, help="Debug capture directories")
    parser.add_argument("--features", action="store_true",
                        help="Show per-channel feature similarity instead of IQ metrics")
    args = parser.parse_args()

    training: dict[str, list[np.ndarray]] = {c: [] for c in ML_CLASSES}
    if args.training:
        print("Loading training data...")
        training = load_training(args.training)
        for cls in ML_CLASSES:
            if training[cls]:
                print(f"  {cls}: {len(training[cls])} samples")
    else:
        print("No training data specified — showing live metrics only.")

    print("\nLoading live captures...")
    live = load_live(args.live)
    for cls, samples in live.items():
        print(f"  {cls}: {len(samples)} samples")

    if args.features:
        print_feature_similarity(training, live)
    else:
        print_comparison(training, live)


if __name__ == "__main__":
    main()
