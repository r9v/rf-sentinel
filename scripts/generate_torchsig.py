"""Generate training data using TorchSig + custom protocol generators.

Runs inside Docker where TorchSig is available. Protocol-specific signals
(LoRa, ADS-B) use pure numpy generators since TorchSig doesn't model these.

Usage (from project root):
    docker build -t torchsig-gpu -f docker/Dockerfile.torchsig-gpu .

    # All classes at once:
    docker run --rm --gpus all -v ./data:/data -v ./scripts:/scripts torchsig-gpu \
        python /scripts/generate_torchsig.py --output /data/synthetic.npz

    # Custom protocols only (fast, no TorchSig needed):
    docker run --rm --gpus all -v ./data:/data -v ./scripts:/scripts torchsig-gpu \
        python /scripts/generate_torchsig.py --classes custom --output /data/synthetic_custom.npz

Classes (indices match ML_CLASSES order):
    0  fm       Wideband FM broadcast
    1  am       AM-DSB broadcast (airband)
    2  nfm      Narrowband FM voice
    3  ofdm     Multi-carrier digital (DAB+, DVB-T, WiFi)
    4  tdma     Bursty single-carrier digital (TETRA, DMR, GSM)
    5  lora     LoRa chirp spread spectrum
    6  adsb     ADS-B pulsed (1090 MHz)
    7  noise    No signal
"""

from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np

N_IQ = 1024
SAMPLE_RATE = 1_024_000

OUR_CLASSES = (
    "fm", "am", "nfm", "ofdm", "tdma",
    "lora", "adsb", "noise",
)

TORCHSIG_CLASSES = {"fm", "am", "nfm", "ofdm", "tdma", "lora"}
CUSTOM_CLASSES = {"adsb", "noise"}

_IDX = {c: i for i, c in enumerate(OUR_CLASSES)}

# Per-class TorchSig config
_TORCHSIG_CONFIG: dict[str, dict] = {
    "fm": {
        "generators": ["fm"],
        "bw_min": 150_000, "bw_max": 200_000,
        "center_jitter": 0.05,
    },
    "am": {
        "generators": ["am-dsb", "am-dsb-sc"],
        "bw_min": 6_000, "bw_max": 10_000,
        "center_jitter": 0.10,
    },
    "nfm": {
        "generators": ["2fsk", "2gfsk", "2msk", "2gmsk", "4fsk", "4gfsk"],
        "bw_min": 8_000, "bw_max": 25_000,
        "center_jitter": 0.10,
    },
    "ofdm": {
        "generators": [
            "ofdm-64", "ofdm-72", "ofdm-128", "ofdm-180", "ofdm-256",
            "ofdm-300", "ofdm-512", "ofdm-600", "ofdm-900", "ofdm-1024",
            "ofdm-1200", "ofdm-2048",
        ],
        "bw_min": 100_000, "bw_max": int(SAMPLE_RATE * 0.45),
        "center_jitter": 0.05,
    },
    "tdma": {
        "generators": [
            "ook", "4ask", "8ask", "16ask", "32ask", "64ask",
            "bpsk", "qpsk", "8psk", "16psk", "32psk", "64psk",
            "16qam", "32qam", "32qam_cross", "64qam", "128qam_cross",
            "256qam", "512qam_cross", "1024qam",
        ],
        "bw_min": 10_000, "bw_max": 100_000,
        "center_jitter": 0.10,
    },
    "lora": {
        "generators": ["chirpss"],
        "bw_min": 125_000, "bw_max": 250_000,
        "center_jitter": 0.05,
    },
}


# --- Pure numpy protocol generators ---


def _add_noise(iq: np.ndarray, snr_db: float, rng: np.random.Generator) -> np.ndarray:
    sig_power = np.mean(np.abs(iq) ** 2)
    noise_power = sig_power * 10 ** (-snr_db / 10)
    noise = np.sqrt(noise_power / 2) * (
        rng.standard_normal(len(iq)) + 1j * rng.standard_normal(len(iq))
    )
    return iq + noise


def _unit_power(iq: np.ndarray) -> np.ndarray:
    power = np.mean(np.abs(iq) ** 2)
    if power < 1e-12:
        return iq
    return iq / np.sqrt(power)


def _freq_shift(iq: np.ndarray, offset_hz: float) -> np.ndarray:
    if offset_hz == 0:
        return iq
    t = np.arange(len(iq)) / SAMPLE_RATE
    return iq * np.exp(1j * 2 * np.pi * offset_hz * t)


def _augment(iq: np.ndarray, rng: np.random.Generator,
             snr_lo: float = -5, snr_hi: float = 30) -> np.ndarray:
    snr_db = rng.uniform(snr_lo, snr_hi)
    iq = _add_noise(iq, snr_db, rng)
    iq = _freq_shift(iq, rng.uniform(-SAMPLE_RATE * 0.05, SAMPLE_RATE * 0.05))
    iq = iq * np.exp(1j * rng.uniform(0, 2 * np.pi))
    return _unit_power(iq)



def gen_adsb(rng: np.random.Generator) -> np.ndarray:
    """Generate ADS-B Mode S pulsed signal (PPM at 1 Mbit/s)."""
    # ADS-B: 8 µs preamble + 112 bits PPM at 1 µs/bit = 120 µs total
    # At 1.024 MHz sample rate: ~123 samples per message
    sps = SAMPLE_RATE / 1_000_000  # ~1.024 samples per µs

    iq = np.zeros(N_IQ, dtype=np.complex64)

    # Generate 1-3 ADS-B messages at random positions
    n_messages = rng.integers(1, 4)
    for _ in range(n_messages):
        # Preamble: pulses at 0, 1, 3.5, 4.5 µs (each 0.5 µs wide)
        preamble_pulses = [0, 1.0, 3.5, 4.5]
        pulse_width = 0.5  # µs

        # 112-bit message (random data)
        bits = rng.integers(0, 2, size=112)

        # Build envelope
        msg_len_us = 8 + 112  # preamble + data
        msg_samples = int(msg_len_us * sps) + 2
        envelope = np.zeros(msg_samples, dtype=np.float64)

        # Preamble pulses
        for t_us in preamble_pulses:
            s = int(t_us * sps)
            e = int((t_us + pulse_width) * sps)
            envelope[s:min(e, msg_samples)] = 1.0

        # PPM data bits: bit=1 → pulse in first half, bit=0 → pulse in second half
        for i, bit in enumerate(bits):
            bit_start_us = 8.0 + i
            if bit == 1:
                s = int(bit_start_us * sps)
                e = int((bit_start_us + 0.5) * sps)
            else:
                s = int((bit_start_us + 0.5) * sps)
                e = int((bit_start_us + 1.0) * sps)
            if s < msg_samples:
                envelope[s:min(e, msg_samples)] = 1.0

        # Random amplitude and position
        amplitude = rng.uniform(0.5, 1.0)
        pos = rng.integers(0, max(1, N_IQ - msg_samples))
        end = min(pos + len(envelope), N_IQ)
        iq[pos:end] += amplitude * envelope[:end - pos]

    # Modulate onto carrier (OOK — envelope × carrier)
    carrier_offset = rng.uniform(-50e3, 50e3)
    t = np.arange(N_IQ) / SAMPLE_RATE
    iq = iq * np.exp(1j * 2 * np.pi * carrier_offset * t)

    return iq.astype(np.complex64)


# Protocol generator dispatch: class_name → (generator_fn, snr_lo, snr_hi)
_PROTOCOL_GENERATORS: dict[str, tuple] = {
    "adsb":   (gen_adsb,    5, 30),
}


def _generate_protocol_samples(
    class_name: str, count: int, rng: np.random.Generator
) -> list[np.ndarray]:
    gen_fn, snr_lo, snr_hi = _PROTOCOL_GENERATORS[class_name]
    samples = []
    for _ in range(count):
        iq = gen_fn(rng)
        iq = _augment(iq, rng, snr_lo, snr_hi)
        samples.append(iq)
    return samples


# --- TorchSig generation (multiprocessing) ---


def _torchsig_worker(
    cls_name: str,
    cls_idx: int,
    count: int,
    impairment_level: int,
    seed: int,
) -> tuple[int, list[np.ndarray]]:
    """Generate `count` samples of one class using targeted signal_generators."""
    from torchsig.utils.defaults import default_dataset

    cfg = _TORCHSIG_CONFIG[cls_name]
    jitter = cfg["center_jitter"]
    dataset = default_dataset(
        impairment_level=impairment_level,
        signal_generators=cfg["generators"],
        num_iq_samples_dataset=N_IQ,
        sample_rate=float(SAMPLE_RATE),
        num_signals_min=1,
        num_signals_max=1,
        snr_db_min=-5.0,
        snr_db_max=30.0,
        signal_duration_in_samples_min=int(N_IQ * 0.8),
        signal_duration_in_samples_max=N_IQ,
        bandwidth_min=cfg["bw_min"],
        bandwidth_max=cfg["bw_max"],
        signal_center_freq_min=int(-SAMPLE_RATE * jitter),
        signal_center_freq_max=int(SAMPLE_RATE * jitter),
        frequency_min=int(-SAMPLE_RATE * 0.5),
        frequency_max=int(SAMPLE_RATE * 0.5),
    )

    samples: list[np.ndarray] = []
    it = iter(dataset)
    skipped = 0
    t_start = time.time()
    last_log = 0

    while len(samples) < count:
        try:
            signal = next(it)
        except StopIteration:
            it = iter(dataset)
            signal = next(it)
        except (ValueError, RuntimeError):
            skipped += 1
            if skipped > count * 5:
                break
            continue

        iq = np.asarray(signal.data, dtype=np.complex64)
        if len(iq) > N_IQ:
            iq = iq[(len(iq) - N_IQ) // 2:][:N_IQ]
        elif len(iq) < N_IQ:
            skipped += 1
            continue

        samples.append(_unit_power(iq))

        if len(samples) - last_log >= 500:
            last_log = len(samples)
            elapsed = time.time() - t_start
            rate = len(samples) / elapsed if elapsed > 0 else 0
            eta_s = (count - len(samples)) / rate if rate > 0 else 0
            print(f"    {cls_name}: {len(samples)}/{count} "
                  f"({len(samples)*100//count}%) ETA {eta_s:.0f}s"
                  + (f" [{skipped} skipped]" if skipped else ""),
                  flush=True)

    return cls_idx, samples


def _generate_torchsig_samples(
    targets: dict[str, int],
    impairment_level: int,
    seed: int,
    n_workers: int = 1,
) -> dict[int, list[np.ndarray]]:
    """Generate TorchSig samples per class in parallel (one worker per class)."""
    total_needed = sum(targets.values())
    n_classes = len(targets)
    actual_workers = min(n_workers, n_classes)
    print(f"    Generating {total_needed} TorchSig samples "
          f"({n_classes} classes, {actual_workers} workers)...")
    t_start = time.time()

    merged: dict[int, list[np.ndarray]] = {}
    jobs = [(cls_name, _IDX[cls_name], count, impairment_level, seed + i * 1000)
            for i, (cls_name, count) in enumerate(targets.items())]

    if actual_workers <= 1:
        for args in jobs:
            cls_idx, samples = _torchsig_worker(*args)
            merged[cls_idx] = samples
    else:
        with ProcessPoolExecutor(max_workers=actual_workers) as pool:
            futures = {pool.submit(_torchsig_worker, *args): args[0] for args in jobs}
            for f in as_completed(futures):
                cls_name = futures[f]
                cls_idx, samples = f.result()
                merged[cls_idx] = samples
                print(f"    {cls_name} done: {len(samples)} samples")

    elapsed = time.time() - t_start
    total_got = sum(len(s) for s in merged.values())
    print(f"    TorchSig done in {elapsed:.0f}s ({total_got} samples)")

    return merged


# --- Main entry point ---


def _parse_classes(classes_str: str) -> set[str]:
    """Parse --classes argument into a set of class names."""
    if classes_str == "all":
        return set(OUR_CLASSES)
    if classes_str == "torchsig":
        return TORCHSIG_CLASSES
    if classes_str == "custom":
        return CUSTOM_CLASSES
    names = {c.strip() for c in classes_str.split(",")}
    for name in names:
        if name not in set(OUR_CLASSES):
            raise ValueError(f"Unknown class: {name!r}. Valid: {', '.join(OUR_CLASSES)}")
    return names


def generate(
    per_class: dict[str, int] | None = None,
    samples_per_class: int = 5000,
    impairment_level: int = 2,
    output_path: str = "/data/synthetic.npz",
    seed: int = 12345,
    classes: set[str] | None = None,
    n_workers: int = 1,
):
    if classes is None:
        classes = set(OUR_CLASSES)
    counts = {c: per_class.get(c, samples_per_class) for c in classes} if per_class else {c: samples_per_class for c in classes}

    rng = np.random.default_rng(seed)
    t0 = time.time()

    requested_torchsig = classes & TORCHSIG_CLASSES
    requested_custom = classes & CUSTOM_CLASSES

    print(f"Generating impairment_level={impairment_level}, N_IQ={N_IQ}")
    for c in sorted(counts):
        print(f"  {c}: {counts[c]}")
    if n_workers > 1:
        print(f"Workers: {n_workers}")

    all_iq: list[np.ndarray] = []
    all_labels: list[int] = []

    # 1) Protocol-specific classes (pure numpy, fast)
    custom_to_gen = [c for c in _PROTOCOL_GENERATORS if c in requested_custom]
    if custom_to_gen:
        for pi, cls_name in enumerate(custom_to_gen, 1):
            cls_idx = OUR_CLASSES.index(cls_name)
            n = counts[cls_name]
            t1 = time.time()
            print(f"  [{pi}/{len(custom_to_gen)}] Generating {cls_name} ({n} samples)...", end="", flush=True)
            samples = _generate_protocol_samples(cls_name, n, rng)
            print(f" done ({time.time() - t1:.1f}s)")
            for s in samples:
                all_iq.append(s)
                all_labels.append(cls_idx)

    # 2) Noise (pure numpy)
    if "noise" in requested_custom:
        n = counts["noise"]
        print(f"  Generating noise ({n} samples)...", end="", flush=True)
        t1 = time.time()
        noise_idx = OUR_CLASSES.index("noise")
        for _ in range(n):
            noise = (rng.standard_normal(N_IQ) + 1j * rng.standard_normal(N_IQ)).astype(np.complex64)
            all_iq.append(_unit_power(noise))
            all_labels.append(noise_idx)
        print(f" done ({time.time() - t1:.1f}s)")

    # 3) TorchSig classes
    if requested_torchsig:
        torchsig_targets = {c: counts[c] for c in requested_torchsig}
        names = ", ".join(sorted(requested_torchsig))
        print(f"  Generating TorchSig classes ({names})...")
        ts_buckets = _generate_torchsig_samples(
            torchsig_targets, impairment_level, seed, n_workers,
        )

        for cls_idx, samples in ts_buckets.items():
            actual = len(samples)
            cls_name = OUR_CLASSES[cls_idx]
            if actual < torchsig_targets[cls_name]:
                print(f"    WARNING: {cls_name} only got {actual}/{torchsig_targets[cls_name]}")
            for s in samples:
                all_iq.append(s)
                all_labels.append(cls_idx)

    if not all_iq:
        print("No samples generated!")
        return

    # Assemble and shuffle
    all_iq_arr = np.stack(all_iq)
    all_labels_arr = np.array(all_labels, dtype=np.int64)
    perm = rng.permutation(len(all_labels_arr))
    all_iq_arr = all_iq_arr[perm]
    all_labels_arr = all_labels_arr[perm]

    np.savez_compressed(
        output_path,
        iq=all_iq_arr,
        labels=all_labels_arr,
        classes=np.array(OUR_CLASSES),
        sample_rate=np.float64(SAMPLE_RATE),
    )

    elapsed = time.time() - t0
    size_mb = os.path.getsize(output_path) / 1024 / 1024 if os.path.isfile(output_path) else 0

    counts = np.bincount(all_labels_arr, minlength=len(OUR_CLASSES))
    print(f"\nDone in {elapsed:.0f}s — {len(all_labels_arr)} samples, {size_mb:.1f} MB")
    for i, name in enumerate(OUR_CLASSES):
        if counts[i] > 0:
            print(f"  {name:>8s}: {counts[i]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate training data (TorchSig + protocol generators)")
    parser.add_argument("--samples-per-class", type=int, default=5000,
                        help="Default samples per class (overridden by --per-class)")
    parser.add_argument("--per-class", type=str, default=None,
                        help="Per-class counts: 'fm:20000,am:20000,noise:5000'")
    parser.add_argument("--impairment-level", type=int, default=2, choices=[0, 1, 2])
    parser.add_argument("--output", type=str, default="/data/synthetic.npz")
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--classes", type=str, default="all",
                        help="Which classes to generate: 'all', 'torchsig', 'custom', "
                             "or comma-separated names (e.g. 'fm,am,ofdm')")
    parser.add_argument("--workers", type=int, default=1,
                        help="Number of parallel TorchSig workers (default: 1)")
    args = parser.parse_args()

    per_class = None
    if args.per_class:
        per_class = {}
        for pair in args.per_class.split(","):
            name, count = pair.split(":")
            name = name.strip()
            if name not in set(OUR_CLASSES):
                raise ValueError(f"Unknown class: {name!r}")
            per_class[name] = int(count)

    classes = set(per_class.keys()) if per_class else _parse_classes(args.classes)
    generate(
        per_class=per_class,
        samples_per_class=args.samples_per_class,
        impairment_level=args.impairment_level,
        output_path=args.output,
        seed=args.seed,
        classes=classes,
        n_workers=args.workers,
    )
