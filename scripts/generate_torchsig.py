"""Generate training data using TorchSig + custom protocol generators.

Runs inside Docker where TorchSig is available. Protocol-specific signals
(DMR, P25, D-STAR, POCSAG, CW) use pure numpy generators since
TorchSig doesn't model these protocols.

Usage (from project root):
    docker build -t torchsig-gpu -f docker/Dockerfile.torchsig-gpu .

    # All classes at once (original behavior):
    docker run --rm --gpus all -v ./data:/data -v ./scripts:/scripts torchsig-gpu \
        python /scripts/generate_torchsig.py --output /data/synthetic.npz

    # Per-class parallel runs (launch each in a separate terminal):
    docker run --rm --gpus all -v ./data:/data -v ./scripts:/scripts torchsig-gpu \
        python /scripts/generate_torchsig.py --classes fm --output /data/synthetic_fm.npz
    docker run --rm --gpus all -v ./data:/data -v ./scripts:/scripts torchsig-gpu \
        python /scripts/generate_torchsig.py --classes am --output /data/synthetic_am.npz
    # ... etc for ssb, nfm, digital

    # Custom protocols (fast, single run):
    docker run --rm --gpus all -v ./data:/data -v ./scripts:/scripts torchsig-gpu \
        python /scripts/generate_torchsig.py --classes custom --output /data/synthetic_custom.npz

Classes (indices match ML_CLASSES order):
    0  fm       Wideband FM broadcast
    1  am       AM-DSB broadcast
    2  ssb      Single sideband (USB/LSB)
    3  cw       Morse code (OOK carrier)
    4  nfm      Narrowband FM voice
    5  dmr      DMR digital voice (4FSK TDMA)
    6  p25      P25 digital voice (C4FM)
    7  dstar    D-STAR digital voice (GMSK)
    8  lora     LoRa chirp spread spectrum
    9  pocsag   Pager (2FSK)
    10 digital  Generic digital (PSK/QAM/OFDM)
    11 noise    No signal
"""

from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count

import numpy as np

N_IQ = 1024
SAMPLE_RATE = 1_024_000

OUR_CLASSES = (
    "fm", "am", "ssb", "cw", "nfm", "dmr", "p25", "dstar",
    "lora", "pocsag", "digital", "noise",
)

TORCHSIG_CLASSES = {"fm", "am", "ssb", "nfm", "digital"}
CUSTOM_CLASSES = {"cw", "dmr", "p25", "dstar", "lora", "pocsag", "noise"}

# TorchSig class → our class index
_TORCHSIG_MAP: dict[str, int] = {
    "fm": 0,
    "am-dsb": 1, "am-dsb-sc": 1,
    "am-lsb": 2, "am-usb": 2,         # SSB
    # Generic digital modulations → "digital" (index 10)
}
_DIGITAL_TORCHSIG = {
    "ook", "4ask", "8ask", "16ask", "32ask", "64ask",
    "bpsk", "qpsk", "8psk", "16psk", "32psk", "64psk",
    "16qam", "32qam", "32qam_cross", "64qam", "128qam_cross",
    "256qam", "512qam_cross", "1024qam",
    "ofdm-64", "ofdm-72", "ofdm-128", "ofdm-180", "ofdm-256",
    "ofdm-300", "ofdm-512", "ofdm-600", "ofdm-900", "ofdm-1024",
    "ofdm-1200", "ofdm-2048",
}
for cls in _DIGITAL_TORCHSIG:
    _TORCHSIG_MAP[cls] = 10

# NFM-like modulations (narrow FSK/MSK) → nfm (index 4)
for cls in ("2fsk", "2gfsk", "2msk", "2gmsk", "4fsk", "4gfsk"):
    _TORCHSIG_MAP[cls] = 4


# --- Pure numpy protocol generators (TorchSig doesn't model these) ---


def _bandlimit(signal: np.ndarray, cutoff_hz: float) -> np.ndarray:
    n = len(signal)
    freqs = np.fft.fftfreq(n, 1 / SAMPLE_RATE)
    spectrum = np.fft.fft(signal)
    spectrum[np.abs(freqs) > cutoff_hz] = 0
    return np.fft.ifft(spectrum)


def _gaussian_filter(n_taps: int, bt: float, sps: int) -> np.ndarray:
    t = np.arange(n_taps) / sps - n_taps / (2 * sps)
    alpha = np.sqrt(np.log(2) / 2) / bt
    h = np.sqrt(np.pi) / alpha * np.exp(-(np.pi * t / alpha) ** 2)
    return h / h.sum()


def _fsk_modulate(symbols: np.ndarray, sps: int,
                  deviation_hz: float, gaussian_bt: float = 0) -> np.ndarray:
    freq_pulses = np.repeat(symbols.astype(np.float64), sps)
    if gaussian_bt > 0:
        g = _gaussian_filter(4 * sps, gaussian_bt, sps)
        freq_pulses = np.convolve(freq_pulses, g, mode="same")
    phase = 2 * np.pi * deviation_hz * np.cumsum(freq_pulses) / SAMPLE_RATE
    return np.exp(1j * phase).astype(np.complex64)


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


def gen_cw(rng: np.random.Generator) -> np.ndarray:
    wpm = rng.uniform(10, 30)
    dit_samples = int(SAMPLE_RATE * 1.2 / wpm)
    envelope = np.zeros(N_IQ + dit_samples * 10, dtype=np.float64)
    pos = 0
    while pos < N_IQ:
        length = dit_samples if rng.random() < 0.6 else dit_samples * 3
        end = min(pos + length, len(envelope))
        envelope[pos:end] = 1.0
        pos = end + dit_samples
        if rng.random() < 0.3:
            pos += dit_samples * 2
    envelope = envelope[:N_IQ]
    ramp_len = max(4, dit_samples // 8)
    ramp = 0.5 * (1 - np.cos(np.pi * np.arange(ramp_len) / ramp_len))
    diff = np.diff(envelope, prepend=0)
    for i in np.where(diff > 0.5)[0]:
        end = min(i + ramp_len, N_IQ)
        envelope[i:end] = ramp[:end - i]
    for i in np.where(diff < -0.5)[0]:
        start = max(i - ramp_len, 0)
        envelope[start:i] = ramp[:i - start][::-1]
    tone_offset = rng.uniform(400, 1000)
    t = np.arange(N_IQ) / SAMPLE_RATE
    return (envelope * np.exp(1j * 2 * np.pi * tone_offset * t)).astype(np.complex64)


def gen_dmr(rng: np.random.Generator) -> np.ndarray:
    sps = int(SAMPLE_RATE / 4800)
    n_sym = (N_IQ // sps) + 4
    symbols = rng.choice([-3, -1, 1, 3], size=n_sym).astype(np.float64)
    return _fsk_modulate(symbols, sps, 648.0, gaussian_bt=0.5)[:N_IQ]


def gen_p25(rng: np.random.Generator) -> np.ndarray:
    sps = int(SAMPLE_RATE / 4800)
    n_sym = (N_IQ // sps) + 4
    symbols = rng.choice([-3, -1, 1, 3], size=n_sym).astype(np.float64)
    return _fsk_modulate(symbols, sps, 600.0, gaussian_bt=0.2)[:N_IQ]


def gen_dstar(rng: np.random.Generator) -> np.ndarray:
    sps = int(SAMPLE_RATE / 4800)
    n_sym = (N_IQ // sps) + 4
    symbols = rng.choice([-1, 1], size=n_sym).astype(np.float64)
    return _fsk_modulate(symbols, sps, 1200.0, gaussian_bt=0.5)[:N_IQ]


def gen_lora(rng: np.random.Generator) -> np.ndarray:
    sf = rng.integers(7, 13)
    bw = rng.choice([125e3, 250e3])
    n_chips = 2 ** sf
    chirp_duration = n_chips / bw
    spc = max(4, int(SAMPLE_RATE * chirp_duration))
    iq = np.zeros(N_IQ + spc, dtype=np.complex64)
    pos = 0
    while pos < N_IQ:
        symbol = rng.integers(0, n_chips)
        f_start = -bw / 2 + (symbol / n_chips) * bw
        t = np.arange(spc) / SAMPLE_RATE
        freq = f_start + (bw / chirp_duration) * t
        freq = ((freq + bw / 2) % bw) - bw / 2
        phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
        chirp = np.exp(1j * phase).astype(np.complex64)
        end = min(pos + spc, len(iq))
        iq[pos:end] = chirp[:end - pos]
        pos += spc
    return iq[:N_IQ]


def gen_pocsag(rng: np.random.Generator) -> np.ndarray:
    baud = rng.choice([512, 1200, 2400])
    spb = max(1, int(SAMPLE_RATE / baud))
    n_bits = max(16, (N_IQ // spb) + 4)
    preamble_bits = min(8, n_bits // 2)
    bits = rng.choice([-1.0, 1.0], size=n_bits)
    bits[:preamble_bits] = np.tile([1, -1], preamble_bits // 2 + 1)[:preamble_bits]
    return _fsk_modulate(bits, spb, 4500.0, gaussian_bt=0)[:N_IQ]



# Protocol generator dispatch: class_name → (generator_fn, snr_lo, snr_hi)
_PROTOCOL_GENERATORS: dict[str, tuple] = {
    "cw":     (gen_cw,     -5, 20),
    "dmr":    (gen_dmr,     0, 30),
    "p25":    (gen_p25,     0, 30),
    "dstar":  (gen_dstar,   0, 30),
    "lora":   (gen_lora,  -20, 15),
    "pocsag": (gen_pocsag,  5, 35),
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
    worker_id: int,
    target_per_class: dict[int, int],
    impairment_level: int,
    seed: int,
) -> dict[int, list[np.ndarray]]:
    """Worker process: creates own TorchSig dataset, iterates and collects samples."""
    from torchsig.utils.defaults import default_dataset

    dataset = default_dataset(
        impairment_level=impairment_level,
        num_iq_samples_dataset=N_IQ,
        sample_rate=float(SAMPLE_RATE),
        num_signals_min=1,
        num_signals_max=1,
        snr_db_min=-5.0,
        snr_db_max=30.0,
        signal_duration_in_samples_min=int(N_IQ * 0.8),
        signal_duration_in_samples_max=N_IQ,
        bandwidth_min=5_000,
        bandwidth_max=int(SAMPLE_RATE * 0.45),
        signal_center_freq_min=int(-SAMPLE_RATE * 0.05),
        signal_center_freq_max=int(SAMPLE_RATE * 0.05),
        frequency_min=int(-SAMPLE_RATE * 0.5),
        frequency_max=int(SAMPLE_RATE * 0.5),
    )

    buckets: dict[int, list[np.ndarray]] = {i: [] for i in target_per_class}
    it = iter(dataset)
    total_needed = sum(target_per_class.values())
    max_attempts = total_needed * 20
    skipped = 0
    kept = 0
    t_start = time.time()
    last_log = 0

    for _ in range(max_attempts):
        if all(len(buckets[i]) >= target_per_class[i] for i in target_per_class):
            break
        try:
            signal = next(it)
        except StopIteration:
            it = iter(dataset)
            signal = next(it)
        except (ValueError, RuntimeError):
            skipped += 1
            continue

        try:
            class_name = signal.component_signals[0].to_dict()["_metadata"]["class_name"]
        except (IndexError, KeyError, AttributeError):
            skipped += 1
            continue

        cls_idx = _TORCHSIG_MAP.get(class_name)
        if cls_idx is None or cls_idx not in target_per_class:
            continue
        if len(buckets[cls_idx]) >= target_per_class[cls_idx]:
            continue

        iq = np.asarray(signal.data, dtype=np.complex64)
        if len(iq) > N_IQ:
            iq = iq[(len(iq) - N_IQ) // 2:][:N_IQ]
        elif len(iq) < N_IQ:
            continue

        buckets[cls_idx].append(_unit_power(iq))
        kept += 1

        if kept - last_log >= 500:
            last_log = kept
            done = sum(min(len(buckets[i]), target_per_class[i]) for i in target_per_class)
            elapsed = time.time() - t_start
            rate = done / elapsed if elapsed > 0 else 0
            eta_s = (total_needed - done) / rate if rate > 0 else 0
            counts = {OUR_CLASSES[i]: len(b) for i, b in buckets.items()}
            tag = f"W{worker_id}" if worker_id > 0 else "TorchSig"
            print(f"    {tag}: {done}/{total_needed} ({done*100//total_needed}%) "
                  f"ETA {eta_s/60:.1f}m — {counts}"
                  + (f" [{skipped} skipped]" if skipped else ""),
                  flush=True)

    return buckets


def _generate_torchsig_samples(
    target_per_class: dict[int, int],
    impairment_level: int,
    seed: int,
    n_workers: int = 1,
) -> dict[int, list[np.ndarray]]:
    """Spawn workers to generate TorchSig samples in parallel."""
    total_needed = sum(target_per_class.values())

    # Split targets evenly across workers
    worker_targets = []
    for w in range(n_workers):
        wt = {}
        for cls_idx, count in target_per_class.items():
            base = count // n_workers
            extra = 1 if w < (count % n_workers) else 0
            wt[cls_idx] = base + extra
        worker_targets.append(wt)

    print(f"    Spawning {n_workers} TorchSig worker(s) for {total_needed} total samples...")
    t_start = time.time()

    merged: dict[int, list[np.ndarray]] = {i: [] for i in target_per_class}

    if n_workers == 1:
        result = _torchsig_worker(0, worker_targets[0], impairment_level, seed)
        for cls_idx, samples in result.items():
            merged[cls_idx].extend(samples)
    else:
        with ProcessPoolExecutor(max_workers=n_workers) as pool:
            futures = {}
            for w in range(n_workers):
                f = pool.submit(
                    _torchsig_worker, w, worker_targets[w],
                    impairment_level, seed + w * 1000,
                )
                futures[f] = w

            for f in as_completed(futures):
                w = futures[f]
                result = f.result()
                counts = {OUR_CLASSES[i]: len(s) for i, s in result.items()}
                print(f"    Worker {w} done: {counts}")
                for cls_idx, samples in result.items():
                    merged[cls_idx].extend(samples)

    elapsed = time.time() - t_start
    total_got = sum(len(s) for s in merged.values())
    print(f"    TorchSig done in {elapsed:.0f}s ({total_got} samples, {n_workers} workers)")

    # Trim to exact target counts
    for cls_idx in merged:
        if len(merged[cls_idx]) > target_per_class[cls_idx]:
            merged[cls_idx] = merged[cls_idx][:target_per_class[cls_idx]]

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
    samples_per_class: int = 5000,
    impairment_level: int = 2,
    output_path: str = "/data/synthetic.npz",
    seed: int = 12345,
    classes: set[str] | None = None,
    n_workers: int = 1,
):
    if classes is None:
        classes = set(OUR_CLASSES)

    rng = np.random.default_rng(seed)
    t0 = time.time()

    requested_torchsig = classes & TORCHSIG_CLASSES
    requested_custom = classes & CUSTOM_CLASSES

    print(f"Generating {samples_per_class} samples/class, "
          f"impairment_level={impairment_level}, N_IQ={N_IQ}")
    print(f"Classes: {', '.join(sorted(classes))}")
    if n_workers > 1:
        print(f"Workers: {n_workers}")

    all_iq: list[np.ndarray] = []
    all_labels: list[int] = []

    # 1) Protocol-specific classes (pure numpy, fast)
    custom_to_gen = [c for c in _PROTOCOL_GENERATORS if c in requested_custom]
    if custom_to_gen:
        for pi, cls_name in enumerate(custom_to_gen, 1):
            cls_idx = OUR_CLASSES.index(cls_name)
            t1 = time.time()
            print(f"  [{pi}/{len(custom_to_gen)}] Generating {cls_name} ({samples_per_class} samples)...", end="", flush=True)
            samples = _generate_protocol_samples(cls_name, samples_per_class, rng)
            print(f" done ({time.time() - t1:.1f}s)")
            for s in samples:
                all_iq.append(s)
                all_labels.append(cls_idx)

    # 2) Noise (pure numpy)
    if "noise" in requested_custom:
        print(f"  Generating noise ({samples_per_class} samples)...", end="", flush=True)
        t1 = time.time()
        noise_idx = OUR_CLASSES.index("noise")
        for _ in range(samples_per_class):
            noise = (rng.standard_normal(N_IQ) + 1j * rng.standard_normal(N_IQ)).astype(np.complex64)
            all_iq.append(_unit_power(noise))
            all_labels.append(noise_idx)
        print(f" done ({time.time() - t1:.1f}s)")

    # 3) TorchSig classes
    if requested_torchsig:
        cls_name_to_idx = {"fm": 0, "am": 1, "ssb": 2, "nfm": 4, "digital": 10}
        torchsig_targets = {
            cls_name_to_idx[c]: samples_per_class
            for c in requested_torchsig
        }
        names = ", ".join(sorted(requested_torchsig))
        print(f"  Generating TorchSig classes ({names})...")
        ts_buckets = _generate_torchsig_samples(
            torchsig_targets, impairment_level, seed, n_workers,
        )

        for cls_idx, samples in ts_buckets.items():
            actual = len(samples)
            target = torchsig_targets[cls_idx]
            if actual < target:
                print(f"    WARNING: {OUR_CLASSES[cls_idx]} only got {actual}/{target}")
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
    parser.add_argument("--samples-per-class", type=int, default=5000)
    parser.add_argument("--impairment-level", type=int, default=2, choices=[0, 1, 2])
    parser.add_argument("--output", type=str, default="/data/synthetic.npz")
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--classes", type=str, default="all",
                        help="Which classes to generate: 'all', 'torchsig', 'custom', "
                             "or comma-separated names (e.g. 'fm,am,ssb')")
    parser.add_argument("--workers", type=int, default=1,
                        help="Number of parallel TorchSig workers (default: 1)")
    args = parser.parse_args()
    generate(
        samples_per_class=args.samples_per_class,
        impairment_level=args.impairment_level,
        output_path=args.output,
        seed=args.seed,
        classes=_parse_classes(args.classes),
        n_workers=args.workers,
    )
