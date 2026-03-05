"""Train signal classifier with stratified k-fold CV and export to ONNX.

Usage:
    python -m core.ml.train --data data/training.npz data/radioml.npz data/subghz.npz \
        [--epochs 50] [--folds 5] [--output data/models/classifier.onnx]
"""

from __future__ import annotations

import argparse
import os
import time
import warnings

import numpy as np
import torch
import torch.nn as nn
from sklearn.model_selection import StratifiedKFold
from torch.optim import Adam
from torch.optim.lr_scheduler import CosineAnnealingLR
from torch.utils.data import DataLoader, Subset

from .dataset import IQDataset, augment_channels
from .features import N_CHANNELS, N_IQ
from .model import ML_CLASSES, N_CLASSES, SignalCNN

DEFAULT_OUTPUT = os.path.join("data", "models", "classifier.onnx")


def train(
    data_paths: list[str],
    epochs: int = 50,
    n_folds: int = 5,
    batch_size: int = 1024,
    lr: float = 1e-3,
    weight_decay: float = 1e-4,
    label_smoothing: float = 0.1,
    dropout: float = 0.3,
    test_fraction: float = 0.15,
    output_path: str = DEFAULT_OUTPUT,
):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    t0 = time.time()
    full_dataset = IQDataset(data_paths, augment=False)
    print(f"  Loaded in {time.time() - t0:.1f}s")

    labels = full_dataset.labels
    indices = np.arange(len(labels))

    # --- Held-out test set (stratified) ---
    rng = np.random.default_rng(42)
    test_indices = []
    trainval_indices = []
    for c in range(N_CLASSES):
        class_idx = indices[labels == c]
        rng.shuffle(class_idx)
        n_test = max(1, int(len(class_idx) * test_fraction))
        test_indices.append(class_idx[:n_test])
        trainval_indices.append(class_idx[n_test:])

    test_indices = np.concatenate(test_indices)
    trainval_indices = np.concatenate(trainval_indices)
    trainval_labels = labels[trainval_indices]

    print(f"\nHeld-out test set: {len(test_indices)} samples")
    print(f"Train+val pool:   {len(trainval_indices)} samples")

    # --- Stratified K-Fold on train+val ---
    skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=42)
    fold_results = []

    for fold, (train_rel, val_rel) in enumerate(skf.split(trainval_indices, trainval_labels)):
        fold_start = time.time()
        print(f"\n{'='*60}")
        print(f"  FOLD {fold + 1}/{n_folds}")
        print(f"{'='*60}")

        train_idx = trainval_indices[train_rel]
        val_idx = trainval_indices[val_rel]

        train_set = _SubsetWithAugment(full_dataset, train_idx, augment=True)
        val_set = Subset(full_dataset, val_idx)

        train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True,
                                   num_workers=0, pin_memory=True)
        val_loader = DataLoader(val_set, batch_size=batch_size,
                                num_workers=0, pin_memory=True)

        model = SignalCNN(dropout=dropout).to(device)
        if fold == 0:
            n_params = sum(p.numel() for p in model.parameters())
            print(f"Model: {n_params:,} parameters (dropout={dropout})")

        optimizer = Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
        scheduler = CosineAnnealingLR(optimizer, T_max=epochs)
        criterion = nn.CrossEntropyLoss(label_smoothing=label_smoothing)

        best_acc = 0.0
        best_state = None
        scaler = torch.amp.GradScaler("cuda", enabled=(device.type == "cuda"))

        for epoch in range(epochs):
            # Train
            model.train()
            train_loss = 0.0
            train_correct = 0
            train_total = 0
            for batch_iq, batch_labels in train_loader:
                batch_iq = batch_iq.to(device)
                batch_labels = batch_labels.to(device)
                optimizer.zero_grad()
                with torch.amp.autocast("cuda", enabled=(device.type == "cuda")):
                    logits = model(batch_iq)
                    loss = criterion(logits, batch_labels)
                scaler.scale(loss).backward()
                scaler.step(optimizer)
                scaler.update()
                train_loss += loss.item() * len(batch_labels)
                train_correct += (logits.argmax(1) == batch_labels).sum().item()
                train_total += len(batch_labels)
            scheduler.step()

            # Validate
            model.eval()
            val_correct = 0
            val_total = 0
            class_correct = np.zeros(N_CLASSES)
            class_total = np.zeros(N_CLASSES)
            with torch.no_grad(), torch.amp.autocast("cuda", enabled=(device.type == "cuda")):
                for batch_iq, batch_labels in val_loader:
                    batch_iq = batch_iq.to(device)
                    batch_labels = batch_labels.to(device)
                    logits = model(batch_iq)
                    preds = logits.argmax(1)
                    val_correct += (preds == batch_labels).sum().item()
                    val_total += len(batch_labels)
                    for c in range(N_CLASSES):
                        mask = batch_labels == c
                        class_total[c] += mask.sum().item()
                        class_correct[c] += (preds[mask] == c).sum().item()

            train_acc = train_correct / max(1, train_total)
            val_acc = val_correct / max(1, val_total)
            avg_loss = train_loss / max(1, train_total)

            per_class = ""
            for c in range(N_CLASSES):
                acc = class_correct[c] / max(1, class_total[c])
                per_class += f" {ML_CLASSES[c]}={acc:.0%}"

            print(f"  [{epoch+1:3d}/{epochs}] loss={avg_loss:.4f}  train={train_acc:.1%}  val={val_acc:.1%} |{per_class}")

            if val_acc > best_acc:
                best_acc = val_acc
                best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

        fold_results.append((best_acc, best_state))
        fold_elapsed = time.time() - fold_start
        print(f"  Fold {fold + 1} best val accuracy: {best_acc:.1%} ({fold_elapsed:.0f}s)")

        # Checkpoint best model so far
        checkpoint_path = output_path.replace(".onnx", f"_fold{fold+1}.pt")
        torch.save(best_state, checkpoint_path)
        print(f"  Checkpoint saved: {checkpoint_path}")

    # --- Select best fold ---
    fold_accs = [acc for acc, _ in fold_results]
    mean_acc = np.mean(fold_accs)
    std_acc = np.std(fold_accs)
    best_fold = int(np.argmax(fold_accs))
    print(f"\n{'='*60}")
    print(f"K-Fold results: {' '.join(f'{a:.1%}' for a in fold_accs)}")
    print(f"Mean: {mean_acc:.1%} ± {std_acc:.1%}")
    print(f"Using fold {best_fold + 1} (best: {fold_accs[best_fold]:.1%})")

    model = SignalCNN(dropout=dropout).cpu()
    model.load_state_dict(fold_results[best_fold][1])
    model.eval()

    # --- Evaluate on held-out test set ---
    print(f"\n{'='*60}")
    print(f"  HELD-OUT TEST SET ({len(test_indices)} samples)")
    print(f"{'='*60}")
    test_set = Subset(full_dataset, test_indices)
    test_loader = DataLoader(test_set, batch_size=batch_size, num_workers=0)

    _evaluate_and_print(model, test_loader, "Test")

    # Export ONNX
    _export_onnx(model, output_path)
    _verify_onnx(model, output_path)

    total_elapsed = time.time() - t0
    m, s = divmod(int(total_elapsed), 60)
    h, m = divmod(m, 60)
    print(f"\nTotal training time: {h}h {m}m {s}s")


class _SubsetWithAugment(torch.utils.data.Dataset):
    def __init__(self, dataset: IQDataset, indices: np.ndarray, augment: bool):
        self.dataset = dataset
        self.indices = indices
        self.augment = augment
        self._rng = np.random.default_rng()

    def __len__(self):
        return len(self.indices)

    def __getitem__(self, idx):
        real_idx = self.indices[idx]
        channels = self.dataset.features[real_idx].copy()
        if self.augment:
            channels = augment_channels(channels, self._rng)
        return torch.from_numpy(channels), int(self.dataset.labels[real_idx])


def _evaluate_and_print(model: nn.Module, loader: DataLoader, label: str):
    confusion = np.zeros((N_CLASSES, N_CLASSES), dtype=int)
    correct = 0
    total = 0
    with torch.no_grad():
        for batch_iq, batch_labels in loader:
            preds = model(batch_iq).argmax(1)
            correct += (preds == batch_labels).sum().item()
            total += len(batch_labels)
            for true, pred in zip(batch_labels.numpy(), preds.numpy()):
                confusion[true][pred] += 1

    acc = correct / max(1, total)
    print(f"\n{label} accuracy: {acc:.1%}")

    per_class = ""
    for c in range(N_CLASSES):
        c_total = confusion[c].sum()
        c_acc = confusion[c][c] / max(1, c_total)
        per_class += f"  {ML_CLASSES[c]}={c_acc:.0%}"
    print(f"Per-class:{per_class}")

    header = "     " + "  ".join(f"{ML_CLASSES[c]:>5s}" for c in range(N_CLASSES))
    print(f"\nConfusion matrix:\n{header}")
    for r in range(N_CLASSES):
        row = "  ".join(f"{confusion[r][c]:5d}" for c in range(N_CLASSES))
        print(f"{ML_CLASSES[r]:>5s} {row}")


def _export_onnx(model: nn.Module, output_path: str):
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    dummy = torch.randn(1, N_CHANNELS, N_IQ)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", "You are using the legacy TorchScript")
        torch.onnx.export(
            model, dummy, output_path,
            input_names=["iq"],
            output_names=["logits"],
            dynamic_axes={"iq": {0: "batch"}, "logits": {0: "batch"}},
            opset_version=18,
            dynamo=False,
        )
    size_kb = os.path.getsize(output_path) / 1024
    print(f"\nONNX exported: {output_path} ({size_kb:.0f} KB)")


def _verify_onnx(model: nn.Module, output_path: str):
    try:
        import onnxruntime as ort
    except ImportError:
        print("onnxruntime not installed — skipping ONNX verification")
        return

    session = ort.InferenceSession(output_path, providers=["CPUExecutionProvider"])
    dummy = np.random.randn(4, N_CHANNELS, N_IQ).astype(np.float32)

    with torch.no_grad():
        pt_out = model(torch.from_numpy(dummy)).numpy()
    onnx_out = session.run(None, {"iq": dummy})[0]

    diff = np.max(np.abs(pt_out - onnx_out))
    ok = diff < 1e-4
    print(f"ONNX verification: max diff={diff:.2e} {'OK' if ok else 'MISMATCH'}")


def main():
    parser = argparse.ArgumentParser(description="Train RF signal classifier")
    parser.add_argument("--data", type=str, nargs="+", required=True,
                        help=".npz files from generate_torchsig.py")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--label-smoothing", type=float, default=0.1)
    parser.add_argument("--dropout", type=float, default=0.3)
    parser.add_argument("--output", type=str, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    train(
        data_paths=args.data,
        epochs=args.epochs,
        n_folds=args.folds,
        batch_size=args.batch_size,
        lr=args.lr,
        weight_decay=args.weight_decay,
        label_smoothing=args.label_smoothing,
        dropout=args.dropout,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
