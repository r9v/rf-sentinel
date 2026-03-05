"""Convert Sub-GHz IQ dataset (.mat files) to training .npz format.

Reads .mat files from the Sub-GHz IQ dataset, slices them into 1024-sample
windows, maps signal types to our 13-class scheme, and saves as .npz.

Usage:
    python scripts/convert_subghz.py \
        --input "core/ml/Sub-GHz IQ dataset" \
        --output data/subghz.npz \
        --samples-per-class 5000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import scipy.io

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.ml.features import N_IQ
from core.ml.model import ML_CLASSES

CLASS_MAP = {
    "lorasf7": "lora",
    "lorasf12": "lora",
    "noise": "noise",
    "zigbee": "digital",
    "sigfox": "digital",
    "80211ah": "digital",
    "sunofdm": "digital",
}


def parse_signal_type(filename: str) -> str | None:
    """Extract signal type prefix from a .mat filename."""
    name = filename.lower()
    for prefix in CLASS_MAP:
        if name.startswith(prefix):
            return prefix
    return None


def load_and_slice(mat_path: Path, n_iq: int = N_IQ) -> np.ndarray:
    """Load a .mat file and slice into (M, n_iq) complex64 windows."""
    data = scipy.io.loadmat(str(mat_path))
    iq = data["IQ_samples"].flatten().astype(np.complex64)
    # Normalize to unit power
    power = np.mean(np.abs(iq) ** 2)
    if power > 0:
        iq /= np.sqrt(power)
    n_windows = len(iq) // n_iq
    iq = iq[:n_windows * n_iq].reshape(n_windows, n_iq)
    return iq


def main():
    parser = argparse.ArgumentParser(description="Convert Sub-GHz IQ dataset to .npz")
    parser.add_argument("--input", type=str, required=True, help="Path to dataset root")
    parser.add_argument("--output", type=str, default="data/subghz.npz")
    parser.add_argument("--samples-per-class", type=int, default=5000,
                        help="Max samples per class (balanced sampling)")
    args = parser.parse_args()

    root = Path(args.input)
    mat_files = list(root.rglob("*.mat"))
    print(f"Found {len(mat_files)} .mat files")

    class_to_idx = {c: i for i, c in enumerate(ML_CLASSES)}
    bins: dict[str, list[np.ndarray]] = {c: [] for c in CLASS_MAP.values()}

    for mat_path in mat_files:
        sig_type = parse_signal_type(mat_path.stem)
        if sig_type is None:
            print(f"  Skipping unknown: {mat_path.name}")
            continue
        our_class = CLASS_MAP[sig_type]
        windows = load_and_slice(mat_path)
        bins[our_class].append(windows)
        print(f"  {mat_path.name} -> {our_class} ({len(windows)} windows)")

    all_iq = []
    all_labels = []
    cap = args.samples_per_class

    for cls_name, chunks in bins.items():
        if not chunks:
            continue
        rng = np.random.default_rng(42)
        total_windows = sum(len(c) for c in chunks)
        n_take = min(cap, total_windows)
        chosen = rng.choice(total_windows, size=n_take, replace=False)
        chosen.sort()
        # Map flat indices to (chunk_idx, offset) without full concatenation
        sampled_list = []
        offset = 0
        for chunk in chunks:
            in_chunk = chosen[(chosen >= offset) & (chosen < offset + len(chunk))] - offset
            if len(in_chunk) > 0:
                sampled_list.append(chunk[in_chunk])
            offset += len(chunk)
        sampled = np.concatenate(sampled_list)
        label = class_to_idx[cls_name]
        all_iq.append(sampled)
        all_labels.append(np.full(len(sampled), label, dtype=np.int64))
        print(f"  {cls_name}: {len(sampled)} samples (label={label})")

    iq = np.concatenate(all_iq)
    labels = np.concatenate(all_labels)

    rng = np.random.default_rng(123)
    perm = rng.permutation(len(iq))
    iq = iq[perm]
    labels = labels[perm]

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(str(out_path), iq=iq, labels=labels)
    print(f"\nSaved {len(labels)} samples to {out_path}")
    print(f"Classes present: {sorted(set(ML_CLASSES[l] for l in labels))}")


if __name__ == "__main__":
    main()
