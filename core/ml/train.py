"""Train signal classifier and export to ONNX.

Usage:
    python -m core.ml.train [--epochs 30] [--samples-per-class 10000] [--output data/models/classifier.onnx]
"""

from __future__ import annotations

import argparse
import os
import time
import warnings

import numpy as np
import torch
import torch.nn as nn
from torch.optim import Adam
from torch.optim.lr_scheduler import CosineAnnealingLR
from torch.utils.data import DataLoader, random_split

from .dataset import SignalDataset
from .features import N_CHANNELS
from .model import ML_CLASSES, N_CLASSES, SignalCNN

DEFAULT_OUTPUT = os.path.join("data", "models", "classifier.onnx")


def train(
    epochs: int = 30,
    samples_per_class: int = 10000,
    batch_size: int = 256,
    lr: float = 1e-3,
    output_path: str = DEFAULT_OUTPUT,
):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # Generate dataset
    print(f"Generating dataset: {samples_per_class} samples/class, {N_CLASSES} classes ...")
    t0 = time.time()
    dataset = SignalDataset(samples_per_class=samples_per_class)
    print(f"  {len(dataset)} samples in {time.time() - t0:.1f}s")

    # Split
    n_val = int(len(dataset) * 0.2)
    n_train = len(dataset) - n_val
    train_set, val_set = random_split(dataset, [n_train, n_val])
    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_set, batch_size=batch_size, num_workers=0)

    # Model
    model = SignalCNN().to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"Model: {n_params:,} parameters")

    optimizer = Adam(model.parameters(), lr=lr)
    scheduler = CosineAnnealingLR(optimizer, T_max=epochs)
    criterion = nn.CrossEntropyLoss()

    best_acc = 0.0
    best_state = None

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
            logits = model(batch_iq)
            loss = criterion(logits, batch_labels)
            loss.backward()
            optimizer.step()
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
        with torch.no_grad():
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

    print(f"\nBest val accuracy: {best_acc:.1%}")

    # Restore best model
    if best_state:
        model.load_state_dict(best_state)
    model = model.cpu().eval()

    # Confusion matrix
    _print_confusion_matrix(model, val_loader)

    # Export ONNX
    _export_onnx(model, output_path)

    # Verify ONNX matches PyTorch
    _verify_onnx(model, output_path)


def _print_confusion_matrix(model: nn.Module, val_loader: DataLoader):
    confusion = np.zeros((N_CLASSES, N_CLASSES), dtype=int)
    with torch.no_grad():
        for batch_iq, batch_labels in val_loader:
            preds = model(batch_iq).argmax(1)
            for true, pred in zip(batch_labels.numpy(), preds.numpy()):
                confusion[true][pred] += 1

    header = "     " + "  ".join(f"{ML_CLASSES[c]:>5s}" for c in range(N_CLASSES))
    print(f"\nConfusion matrix:\n{header}")
    for r in range(N_CLASSES):
        row = "  ".join(f"{confusion[r][c]:5d}" for c in range(N_CLASSES))
        print(f"{ML_CLASSES[r]:>5s} {row}")


def _export_onnx(model: nn.Module, output_path: str):
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    dummy = torch.randn(1, N_CHANNELS, 4096)
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
    dummy = np.random.randn(4, N_CHANNELS, 4096).astype(np.float32)

    with torch.no_grad():
        pt_out = model(torch.from_numpy(dummy)).numpy()
    onnx_out = session.run(None, {"iq": dummy})[0]

    diff = np.max(np.abs(pt_out - onnx_out))
    ok = diff < 1e-4
    print(f"ONNX verification: max diff={diff:.2e} {'OK' if ok else 'MISMATCH'}")


def main():
    parser = argparse.ArgumentParser(description="Train RF signal classifier")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--samples-per-class", type=int, default=10000)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--output", type=str, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    train(
        epochs=args.epochs,
        samples_per_class=args.samples_per_class,
        batch_size=args.batch_size,
        lr=args.lr,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
