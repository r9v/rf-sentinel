"""Dataset loaders for training the signal classifier.

Loads pre-generated .npz files produced by scripts/generate_torchsig.py
(TorchSig + custom protocol generators running in Docker).

Features are precomputed to disk on first load and memory-mapped for
subsequent access, eliminating per-epoch FFT overhead.

Expected .npz keys:
    iq:     (N, 1024) complex64 — raw IQ samples, unit-power normalized
    labels: (N,) int64 — class indices matching DATA_CLASSES order
"""

from __future__ import annotations

import hashlib
import os
import time

import numpy as np
import torch
from torch.utils.data import Dataset

from .features import N_CHANNELS, N_IQ, iq_to_channels
from .model import ML_CLASSES, N_CLASSES

CACHE_DIR = os.path.join("data", "cache")

# Class order used when .npz data files were generated (12-class).
# Samples with classes not in ML_CLASSES are dropped and labels remapped.
DATA_CLASSES = (
    "fm", "am", "ssb", "cw", "nfm", "dmr", "p25", "dstar",
    "lora", "pocsag", "digital", "noise",
)


def _build_label_remap() -> np.ndarray:
    remap = np.full(len(DATA_CLASSES), -1, dtype=np.int64)
    for old_idx, name in enumerate(DATA_CLASSES):
        if name in ML_CLASSES:
            remap[old_idx] = ML_CLASSES.index(name)
    return remap


def _cache_key(npz_paths: list[str]) -> str:
    parts = []
    for p in sorted(npz_paths):
        parts.append(f"{os.path.abspath(p)}:{os.path.getmtime(p)}")
    parts.append(f"classes:{','.join(ML_CLASSES)}")
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:12]


def precompute_features(npz_paths: list[str]) -> tuple[str, str]:
    """Precompute (N_CHANNELS, N_IQ) feature tensors and cache as .npy."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = _cache_key(npz_paths)
    feat_path = os.path.join(CACHE_DIR, f"features_{key}.npy")
    lbl_path = os.path.join(CACHE_DIR, f"labels_{key}.npy")

    if os.path.exists(feat_path) and os.path.exists(lbl_path):
        print(f"  Using cached features: {feat_path}")
        return feat_path, lbl_path

    print("  Precomputing features (one-time)...")
    remap = _build_label_remap()
    all_iq = []
    all_labels = []
    for path in npz_paths:
        data = np.load(path)
        raw_labels = remap[data["labels"]]
        keep = raw_labels >= 0
        all_iq.append(data["iq"][keep])
        all_labels.append(raw_labels[keep])
        dropped = int((~keep).sum())
        if dropped:
            print(f"    {path}: kept {int(keep.sum())}, dropped {dropped}")

    iq = np.concatenate(all_iq)
    labels = np.concatenate(all_labels)
    N = len(iq)

    features = np.empty((N, N_CHANNELS, N_IQ), dtype=np.float32)
    t0 = time.time()
    for i in range(N):
        sample = iq[i]
        if len(sample) > N_IQ:
            start = (len(sample) - N_IQ) // 2
            sample = sample[start : start + N_IQ]
        features[i] = iq_to_channels(sample)
        if (i + 1) % 50000 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            eta = (N - i - 1) / rate
            print(f"    {i+1}/{N} ({rate:.0f} samples/s, ETA {eta:.0f}s)")

    np.save(feat_path, features)
    np.save(lbl_path, labels)
    elapsed = time.time() - t0
    size_gb = os.path.getsize(feat_path) / 1e9
    print(f"  Cached {N} samples in {elapsed:.0f}s → {feat_path} ({size_gb:.1f} GB)")

    return feat_path, lbl_path


def augment_channels(channels: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Tensor-level augmentation on precomputed (C, N) feature channels."""
    # Time roll (circular shift up to 25%)
    n = channels.shape[1]
    shift = rng.integers(-n // 4, n // 4)
    channels = np.roll(channels, shift, axis=1)

    # Amplitude scaling
    scale = rng.uniform(0.8, 1.2)
    channels = channels * scale

    # Additive noise per channel
    noise_std = rng.uniform(0.01, 0.05)
    channels = channels + rng.standard_normal(channels.shape).astype(np.float32) * noise_std

    return channels


class IQDataset(Dataset):
    """Load precomputed features from memory-mapped .npy cache."""

    def __init__(self, npz_paths: list[str], augment: bool = False):
        feat_path, lbl_path = precompute_features(npz_paths)
        self.features = np.load(feat_path, mmap_mode="r")
        self.labels = np.load(lbl_path)
        self.augment = augment
        self._rng = np.random.default_rng()

        counts = np.bincount(self.labels, minlength=N_CLASSES)
        dist = " ".join(f"{ML_CLASSES[i]}={counts[i]}" for i in range(N_CLASSES))
        print(f"  Loaded {len(self.labels)} samples ({dist})")

    def __len__(self) -> int:
        return len(self.labels)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, int]:
        channels = self.features[idx].copy()
        if self.augment:
            channels = augment_channels(channels, self._rng)
        return torch.from_numpy(channels), int(self.labels[idx])
