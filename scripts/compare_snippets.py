"""Visualize training data per class per dataset, and live debug snippets.

Usage:
    python scripts/compare_snippets.py              # both training + live
    python scripts/compare_snippets.py --live data/debug/fm
    python scripts/compare_snippets.py --per-data
"""

import argparse
import glob
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, ".")
from core.ml.features import N_CHANNELS, N_IQ, iq_to_channels
from core.ml.model import ML_CLASSES

RESOLUTION_GROUPS = [
    ("Full raw",     [(0, "I"), (1, "Q"), (2, "Inst Freq"), (3, "Amplitude")]),
    ("Full derived", [(4, "InstFreq Var"), (5, "Cyclostat"), (6, "Spectrum"), (10, "ACF full")]),
    ("200 kHz",      [(7, "Spectrum"), (11, "ACF 200k")]),
    ("Spec delta",   [(8, "Spectral Delta"), (9, "Spectrum 25k")]),
    ("Discrim",      [(12, "IFreq ACF"), (13, "Env Variance"), (14, "IFreq Hist"), (15, "PAPR")]),
]

_HIST_CHANNELS = {14, 15}

DATASETS = [
    "data/radioml.npz",
    "data/synthetic.npz",
]

DS_COLORS = {
    "radioml": "tab:green",
    "synthetic": "tab:red",
}

CLASS_COLORS = {
    "fm": "#e6194b",
    "am": "#3cb44b",
    "nfm": "#911eb4",
    "ofdm": "#4363d8",
    "tdma": "#f58231",
    "lora": "#fabed4",
    "adsb": "#469990",
    "noise": "#9A6324",
}

DEFAULT_SAMPLES = 6
OUT_DIR = "data/debug"


def _recompute_channels(snippet):
    return iq_to_channels(snippet["iq"])


def load_live_snippets(path, n=DEFAULT_SAMPLES):
    files = sorted(glob.glob(f"{path}/*.npz"))
    if not files:
        print(f"  No .npz found in {path}")
        return {}
    name = os.path.basename(os.path.normpath(path))
    rng = np.random.default_rng(42)
    if len(files) > n:
        files = list(rng.choice(files, n, replace=False))
    snippets = []
    for f in files:
        d = np.load(f)
        fname = os.path.splitext(os.path.basename(f))[0]
        channels = iq_to_channels(d["iq"])
        snippets.append({"path": f, "iq": d["iq"], "channels": channels, "freq_mhz": float(d["freq_mhz"]), "label": fname})
    print(f"  Loaded {len(snippets)} live snippets from {path}")
    return {name: snippets}


def load_training_samples(npz_path, class_name, n=DEFAULT_SAMPLES):
    if not os.path.exists(npz_path):
        return []
    class_idx = ML_CLASSES.index(class_name) if class_name in ML_CLASSES else -1
    if class_idx < 0:
        return []
    data = np.load(npz_path)
    iq_all = data["iq"]
    labels = data["labels"]
    mask = labels == class_idx
    iq_class = iq_all[mask]
    if len(iq_class) == 0:
        return []
    rng = np.random.default_rng(42)
    idxs = rng.choice(len(iq_class), size=min(n, len(iq_class)), replace=False)
    samples = []
    for i in idxs:
        raw = iq_class[i]
        if len(raw) > N_IQ:
            start = (len(raw) - N_IQ) // 2
            raw = raw[start:start + N_IQ]
        power = np.mean(np.abs(raw) ** 2)
        if power > 0:
            raw = raw / np.sqrt(power)
        ch = iq_to_channels(raw)
        samples.append({"iq": raw, "channels": ch})
    return samples



def _make_figure(sample_rows, title, out_path):
    """Create one figure with resolution groups as column blocks.

    sample_rows: [(label, channels, color), ...]
    Each sample gets 4 rows (one per resolution group).
    """
    n_samples = len(sample_rows)
    n_grid_rows = n_samples * len(RESOLUTION_GROUPS)
    max_cols = max(len(g[1]) for g in RESOLUTION_GROUPS)

    fig, axes = plt.subplots(n_grid_rows, max_cols, figsize=(max_cols * 3, 1.2 * n_grid_rows))
    if n_grid_rows == 1:
        axes = axes[np.newaxis, :]

    # Hide all axes first, then show only the ones we use
    for ax_row in axes:
        for ax in ax_row:
            ax.set_visible(False)

    n_groups = len(RESOLUTION_GROUPS)
    for si, (label, channels, color) in enumerate(sample_rows):
        base_row = si * n_groups
        for gi, (res_name, ch_indices) in enumerate(RESOLUTION_GROUPS):
            row = base_row + gi
            for c, (ch_idx, col_name) in enumerate(ch_indices):
                axes[row, c].set_visible(True)
                axes[row, c].plot(channels[ch_idx], linewidth=0.4, color=color)
                if ch_idx not in _HIST_CHANNELS:
                    axes[row, c].set_ylim(-5, 5)
                axes[row, c].tick_params(labelsize=5)
                if c > 0:
                    axes[row, c].set_yticks([])
                axes[row, c].set_title(col_name, fontsize=7)

            if gi == 0:
                axes[row, 0].set_ylabel(f"{label}\n{res_name}", fontsize=6, fontweight="bold")
            else:
                axes[row, 0].set_ylabel(res_name, fontsize=6, style="italic")

    plt.tight_layout(h_pad=0.3)

    # Add separator lines between sample blocks
    for si in range(1, n_samples):
        row_above = si * n_groups - 1
        row_below = si * n_groups
        y_top = axes[row_above, 0].get_position().y0
        y_bot = axes[row_below, 0].get_position().y1
        y_mid = (y_top + y_bot) / 2
        fig.add_artist(plt.Line2D([0.05, 0.95], [y_mid, y_mid],
                                  transform=fig.transFigure, color="gray",
                                  linewidth=0.5, linestyle="--"))
    plt.savefig(out_path, dpi=150)
    print(f"  Saved: {out_path}")
    plt.close()


def plot_dataset_grid(ds_path, classes, n=DEFAULT_SAMPLES):
    ds_name = os.path.basename(ds_path).replace(".npz", "")
    if not os.path.exists(ds_path):
        print(f"  Skipping {ds_name} (not found)")
        return

    sample_rows = []
    for cls in classes:
        samples = load_training_samples(ds_path, cls, n=n)
        color = CLASS_COLORS.get(cls, "tab:gray")
        for i, s in enumerate(samples):
            label = cls if i == 0 else ""
            sample_rows.append((label, s["channels"], color))

    if not sample_rows:
        print(f"  No classes found in {ds_name}")
        return

    suffix = f"_{'_'.join(classes)}" if len(classes) < len(ML_CLASSES) else ""
    _make_figure(sample_rows, None,
                 os.path.join(OUT_DIR, f"dataset_{ds_name}{suffix}.png"))


def plot_live_grid(live_groups):
    for group, snippets in live_groups.items():
        color = CLASS_COLORS.get(group, "tab:blue")
        sample_rows = []
        for s in snippets:
            ch = _recompute_channels(s)
            fname = s.get("label", f"{s['freq_mhz']:.1f}MHz")
            parts = fname.split("_")
            if len(parts) >= 3 and parts[1].isdigit():
                fname = "_".join([parts[0]] + parts[2:])
            sample_rows.append((fname, ch, color))
        if sample_rows:
            _make_figure(sample_rows, f"Live SDR — {group} ({len(snippets)} samples)",
                         os.path.join(OUT_DIR, f"live_{group}.png"))


def plot_class_comparison(cls, live_groups, include_live, n=DEFAULT_SAMPLES):
    ds_samples = []
    for ds in DATASETS:
        samples = load_training_samples(ds, cls, n=n)
        if samples:
            ds_samples.append((ds, samples))

    live_for_class = live_groups.get(cls, []) if include_live else []
    if not ds_samples and not live_for_class:
        return

    sample_rows = []
    if live_for_class:
        for i, s in enumerate(live_for_class[:n]):
            ch = _recompute_channels(s)
            sample_rows.append(("LIVE" if i == 0 else "", ch, "tab:blue"))

    for ds_path, samples in ds_samples:
        ds_name = os.path.basename(ds_path).replace(".npz", "")
        color = DS_COLORS.get(ds_name, "tab:gray")
        for i, s in enumerate(samples[:n]):
            sample_rows.append((ds_name if i == 0 else "", s["channels"], color))

    if not sample_rows:
        return

    _make_figure(sample_rows, f"Class '{cls}' — all sources",
                 os.path.join(OUT_DIR, f"class_{cls}.png"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-data", action="store_true", help="Generate per-dataset grids")
    parser.add_argument("--live", type=str, nargs="+", metavar="DIR", help="Path(s) to live snippets dirs")
    parser.add_argument("--per-class", action="store_true", help="Generate per-class comparison")
    parser.add_argument("-n", "--samples", type=int, default=DEFAULT_SAMPLES, help=f"Samples per class (default: {DEFAULT_SAMPLES})")
    parser.add_argument("-c", "--classes", type=str, nargs="+", metavar="CLS", help="Filter to specific classes (e.g. fm am lora)")
    args = parser.parse_args()

    run_all = not (args.per_data or args.live or args.per_class)

    os.makedirs(OUT_DIR, exist_ok=True)

    all_classes = args.classes if args.classes else list(ML_CLASSES)

    n = args.samples

    if args.per_data or run_all:
        print("\n=== Per-dataset plots ===")
        for ds in DATASETS:
            for cls in all_classes:
                plot_dataset_grid(ds, [cls], n=n)

    live_groups = {}
    if args.live:
        for d in args.live:
            live_groups.update(load_live_snippets(d, n=n))

    if args.live:
        if live_groups:
            print("\n=== Live snippets ===")
            plot_live_grid(live_groups)

    if args.per_class or run_all:
        print("\n=== Per-class comparison ===")
        include_live = bool(live_groups)
        for cls in all_classes:
            plot_class_comparison(cls, live_groups, include_live, n=n)

    print(f"\nDone. Images in {OUT_DIR}/")


if __name__ == "__main__":
    main()
