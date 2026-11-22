"""Synthetic stand-in clips for smoke tests only (no real-world meaning).

"Chainsaw" = a buzzing two-stroke-like harmonic series with throttle wobble
over noise; "environment" = coloured noise with occasional chirps.
"""
import numpy as np

FAKE_MARKER = "SYNTHETIC_NOT_REAL_DATA"


def chainsaw_like(rng, sr=12000, seconds=3.0):
    t = np.arange(int(sr * seconds)) / sr
    f0 = rng.uniform(90, 160) * (1 + 0.08 * np.sin(2 * np.pi * rng.uniform(0.3, 1.5) * t))
    phase = 2 * np.pi * np.cumsum(f0) / sr
    sig = sum(np.sin(k * phase) / k for k in range(1, 25))
    sig = sig / np.max(np.abs(sig)) * rng.uniform(0.05, 0.5)
    return (sig + rng.normal(0, 0.02, t.shape)).astype(np.float32)


def environment_like(rng, sr=12000, seconds=3.0):
    n = int(sr * seconds)
    noise = np.cumsum(rng.normal(0, 1, n))
    noise -= np.convolve(noise, np.ones(200) / 200, mode="same")
    noise = noise / (np.max(np.abs(noise)) + 1e-9) * rng.uniform(0.01, 0.2)
    t = np.arange(n) / sr
    for _ in range(rng.integers(0, 4)):
        c = rng.uniform(0, seconds - 0.2)
        f = rng.uniform(2000, 5000)
        env = np.exp(-((t - c) / 0.03) ** 2)
        noise += 0.1 * env * np.sin(2 * np.pi * f * t)
    return noise.astype(np.float32)


def clips(n, seed=0, sr=12000):
    """Yield (audio, sr, dataset_label) with label 0 = chainsaw like rfcx/frugalai."""
    rng = np.random.default_rng(seed)
    for i in range(n):
        if i % 2 == 0:
            yield chainsaw_like(rng, sr), sr, 0
        else:
            yield environment_like(rng, sr), sr, 1


def save_fake_dataset(path, n_train=80, n_test=24, seed=0, sr=12000):
    """A tiny on-disk dataset shaped like rfcx/frugalai (columns audio, label;
    12 kHz, 3 s, label 0 = chainsaw) for testing prepare_data/train without
    network. Plumbing only, like clips()."""
    from datasets import Audio, ClassLabel, Dataset, DatasetDict, Features

    feats = Features({"audio": Audio(sampling_rate=sr),
                      "label": ClassLabel(names=["chainsaw", "environment"])})

    def split(n, s):
        rows = [{"audio": {"array": a, "sampling_rate": r}, "label": lab} for a, r, lab in clips(n, s, sr)]
        return Dataset.from_list(rows, features=feats)

    DatasetDict({"train": split(n_train, seed), "test": split(n_test, seed + 1)}).save_to_disk(path)
    with open(f"{path}/{FAKE_MARKER}", "w") as f:
        f.write("synthetic stand-in, not rfcx/frugalai\n")
