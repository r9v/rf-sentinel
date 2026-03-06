"""Convert RadioML 2018.01a HDF5 to training .npz format.

Maps 24 RadioML classes to our 8-class scheme and filters to useful SNR range.

Usage:
    python scripts/convert_radioml.py \
        --input "core/ml/archive/GOLD_XYZ_OSC.0001_1024.hdf5" \
        --output data/radioml.npz \
        --samples-per-class 5000 \
        --min-snr -6
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import h5py
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.ml.model import ML_CLASSES

RADIOML_CLASSES = [
    "OOK", "4ASK", "8ASK", "BPSK", "QPSK", "8PSK", "16PSK", "32PSK",
    "16APSK", "32APSK", "64APSK", "128APSK", "16QAM", "32QAM", "64QAM",
    "128QAM", "256QAM", "AM-SSB-WC", "AM-SSB-SC", "AM-DSB-WC", "AM-DSB-SC",
    "FM", "GMSK", "OQPSK",
]

RADIOML_TO_OURS = {
    "FM": "fm",
    # AM-DSB dropped — RadioML AM has broken IQ balance (14:1 vs real 1:1)
    "GMSK": "nfm",
    "OOK": "tdma",
    "OQPSK": "tdma",
    "BPSK": "tdma",
    "QPSK": "tdma",
    "8PSK": "tdma",
    "16PSK": "tdma",
    "32PSK": "tdma",
    "4ASK": "tdma",
    "8ASK": "tdma",
    "16APSK": "tdma",
    "32APSK": "tdma",
    "64APSK": "tdma",
    "128APSK": "tdma",
    "16QAM": "tdma",
    "32QAM": "tdma",
    "64QAM": "tdma",
    "128QAM": "tdma",
    "256QAM": "tdma",
    # SSB dropped — no HF reception with RTL-SDR
    # "AM-SSB-WC": ...,
    # "AM-SSB-SC": ...,
}


def main():
    parser = argparse.ArgumentParser(description="Convert RadioML 2018.01a to .npz")
    parser.add_argument("--input", type=str, required=True)
    parser.add_argument("--output", type=str, default="data/radioml.npz")
    parser.add_argument("--samples-per-class", type=int, default=5000)
    parser.add_argument("--min-snr", type=int, default=-6,
                        help="Minimum SNR in dB (drop very noisy samples)")
    args = parser.parse_args()

    class_to_idx = {c: i for i, c in enumerate(ML_CLASSES)}

    print(f"Loading {args.input} ...")
    f = h5py.File(args.input, "r")
    X = f["X"]  # (N, 1024, 2)
    Y = f["Y"]  # (N, 24) one-hot
    Z = f["Z"]  # (N, 1) SNR

    n_total = X.shape[0]
    print(f"Total samples: {n_total}")

    snr_all = Z[:].flatten()
    y_idx = np.argmax(Y[:], axis=1)

    snr_mask = snr_all >= args.min_snr
    print(f"Samples with SNR >= {args.min_snr} dB: {snr_mask.sum()}")

    bins: dict[str, list[int]] = {}
    for our_cls in set(RADIOML_TO_OURS.values()):
        bins[our_cls] = []

    for i in range(n_total):
        if not snr_mask[i]:
            continue
        rml_cls = RADIOML_CLASSES[y_idx[i]]
        our_cls = RADIOML_TO_OURS.get(rml_cls)
        if our_cls is None:
            continue
        bins[our_cls].append(i)

    print("\nAvailable per class:")
    for cls, indices in sorted(bins.items()):
        print(f"  {cls}: {len(indices)} samples")

    rng = np.random.default_rng(42)
    cap = args.samples_per_class
    all_iq = []
    all_labels = []

    for cls_name, indices in sorted(bins.items()):
        if not indices:
            continue
        chosen = rng.choice(indices, size=min(cap, len(indices)), replace=False)
        chosen.sort()

        # Read in chunks to avoid loading entire dataset
        chunk_size = 1000
        iq_chunks = []
        for start in range(0, len(chosen), chunk_size):
            batch_idx = chosen[start:start + chunk_size]
            raw = X[batch_idx]  # (chunk, 1024, 2)
            iq = raw[:, :, 0] + 1j * raw[:, :, 1]  # (chunk, 1024) complex
            iq_chunks.append(iq.astype(np.complex64))

        iq_arr = np.concatenate(iq_chunks)
        label = class_to_idx[cls_name]
        all_iq.append(iq_arr)
        all_labels.append(np.full(len(iq_arr), label, dtype=np.int64))
        print(f"  {cls_name}: {len(iq_arr)} samples (label={label})")

    f.close()

    iq = np.concatenate(all_iq)
    labels = np.concatenate(all_labels)

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
