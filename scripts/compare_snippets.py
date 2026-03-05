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
from core.ml.dataset import DATA_CLASSES
from core.ml.features import N_CHANNELS, N_IQ, iq_to_channels
from core.ml.model import ML_CLASSES

RESOLUTION_GROUPS = [
    ("Full raw",     [(0, "I"), (1, "Q"), (2, "Inst Freq"), (3, "Amplitude")]),
    ("Full derived", [(4, "InstFreq Var"), (5, "Cyclostat"), (6, "Spectrum"), (10, "ACF full")]),
    ("200 kHz",      [(7, "Spectrum"), (11, "ACF 200k")]),
    ("100 kHz",      [(8, "Spectrum")]),
    ("25 kHz",       [(9, "Spectrum")]),
]

DATASETS = [
    "data/radioml.npz",
    "data/subghz.npz",
    "data/synthetic_5k.npz",
    "data/synthetic_custom.npz",
]

DS_COLORS = {
    "radioml": "tab:green",
    "subghz": "tab:orange",
    "synthetic_5k": "tab:red",
    "synthetic_custom": "tab:purple",
}

CLASS_COLORS = {
    "fm": "#e6194b",
    "am": "#3cb44b",
    "ssb": "#4363d8",
    "cw": "#f58231",
    "nfm": "#911eb4",
    "dmr": "#42d4f4",
    "p25": "#f032e6",
    "dstar": "#bfef45",
    "lora": "#fabed4",
    "pocsag": "#469990",
    "digital": "#dcbeff",
    "noise": "#9A6324",
}

N_SAMPLES = 6
OUT_DIR = "data/debug"


def _recompute_channels(snippet):
    ch = snippet["channels"]
    if ch.shape[0] == N_CHANNELS:
        return ch
    return iq_to_channels(snippet["iq"])


def load_live_snippets(path):
    files = sorted(glob.glob(f"{path}/*.npz"))
    if not files:
        print(f"  No .npz found in {path}")
        return {}
    name = os.path.basename(os.path.normpath(path))
    snippets = []
    for f in files:
        d = np.load(f)
        fname = os.path.splitext(os.path.basename(f))[0]
        snippets.append({"path": f, "iq": d["iq"], "channels": d["channels"], "freq_mhz": float(d["freq_mhz"]), "label": fname})
    print(f"  Loaded {len(snippets)} live snippets from {path}")
    return {name: snippets}


def load_training_samples(npz_path, class_name, n=N_SAMPLES):
    if not os.path.exists(npz_path):
        return []
    class_idx = DATA_CLASSES.index(class_name) if class_name in DATA_CLASSES else -1
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

    for si, (label, channels, color) in enumerate(sample_rows):
        base_row = si * len(RESOLUTION_GROUPS)
        for gi, (res_name, ch_indices) in enumerate(RESOLUTION_GROUPS):
            row = base_row + gi
            for c, (ch_idx, col_name) in enumerate(ch_indices):
                axes[row, c].set_visible(True)
                axes[row, c].plot(channels[ch_idx], linewidth=0.4, color=color)
                axes[row, c].set_ylim(-5, 5)
                axes[row, c].tick_params(labelsize=5)
                if c > 0:
                    axes[row, c].set_yticks([])
                # Column headers on the very first sample's rows
                if si == 0:
                    axes[row, c].set_title(col_name, fontsize=7)

            # Row label: sample label on first resolution row, resolution name on others
            if gi == 0:
                axes[row, 0].set_ylabel(f"{label}\n{res_name}", fontsize=6, fontweight="bold")
            else:
                axes[row, 0].set_ylabel(res_name, fontsize=6, style="italic")

    plt.suptitle(title, fontsize=13)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    print(f"  Saved: {out_path}")
    plt.close()


def plot_dataset_grid(ds_path, classes):
    ds_name = os.path.basename(ds_path).replace(".npz", "")
    if not os.path.exists(ds_path):
        print(f"  Skipping {ds_name} (not found)")
        return

    sample_rows = []
    for cls in classes:
        samples = load_training_samples(ds_path, cls, n=N_SAMPLES)
        color = CLASS_COLORS.get(cls, "tab:gray")
        for i, s in enumerate(samples):
            label = cls if i == 0 else ""
            sample_rows.append((label, s["channels"], color))

    if not sample_rows:
        print(f"  No classes found in {ds_name}")
        return

    _make_figure(sample_rows, f"{ds_name} — {len(classes)} classes",
                 os.path.join(OUT_DIR, f"dataset_{ds_name}.png"))


def plot_live_grid(live_groups):
    sample_rows = []
    prev_group = None
    for group, snippets in live_groups.items():
        color = CLASS_COLORS.get(group, "tab:blue")
        for s in snippets:
            ch = _recompute_channels(s)
            fname = s.get("label", f"{s['freq_mhz']:.1f}MHz")
            parts = fname.split("_")
            if len(parts) >= 3 and parts[1].isdigit():
                fname = "_".join([parts[0]] + parts[2:])
            label = f"{group} {fname}" if group != prev_group else fname
            sample_rows.append((label, ch, color))
            prev_group = group

    if not sample_rows:
        return

    groups_str = ", ".join(f"{k}({len(v)})" for k, v in live_groups.items())
    _make_figure(sample_rows, f"Live SDR snippets — {groups_str}",
                 os.path.join(OUT_DIR, "live_snippets.png"))


def plot_class_comparison(cls, live_groups, include_live):
    ds_samples = []
    for ds in DATASETS:
        samples = load_training_samples(ds, cls, n=N_SAMPLES)
        if samples:
            ds_samples.append((ds, samples))

    live_for_class = live_groups.get(cls, []) if include_live else []
    if not ds_samples and not live_for_class:
        return

    sample_rows = []
    if live_for_class:
        for i, s in enumerate(live_for_class[:N_SAMPLES]):
            ch = _recompute_channels(s)
            sample_rows.append(("LIVE" if i == 0 else "", ch, "tab:blue"))

    for ds_path, samples in ds_samples:
        ds_name = os.path.basename(ds_path).replace(".npz", "")
        color = DS_COLORS.get(ds_name, "tab:gray")
        for i, s in enumerate(samples[:N_SAMPLES]):
            sample_rows.append((ds_name if i == 0 else "", s["channels"], color))

    if not sample_rows:
        return

    _make_figure(sample_rows, f"Class '{cls}' — all sources",
                 os.path.join(OUT_DIR, f"class_{cls}.png"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-data", action="store_true", help="Generate per-dataset grids")
    parser.add_argument("--live", type=str, metavar="DIR", help="Path to live snippets dir (e.g. data/debug/fm)")
    parser.add_argument("--per-class", action="store_true", help="Generate per-class comparison")
    args = parser.parse_args()

    run_all = not (args.per_data or args.live or args.per_class)

    os.makedirs(OUT_DIR, exist_ok=True)

    all_classes = list(ML_CLASSES)

    if args.per_data or run_all:
        print("\n=== Per-dataset plots ===")
        for ds in DATASETS:
            plot_dataset_grid(ds, all_classes)

    live_groups = {}
    if args.live:
        live_groups = load_live_snippets(args.live)

    if args.live:
        if live_groups:
            print("\n=== Live snippets ===")
            plot_live_grid(live_groups)

    if args.per_class or run_all:
        print("\n=== Per-class comparison ===")
        include_live = bool(live_groups)
        for cls in all_classes:
            plot_class_comparison(cls, live_groups, include_live)

    print(f"\nDone. Images in {OUT_DIR}/")


if __name__ == "__main__":
    main()
