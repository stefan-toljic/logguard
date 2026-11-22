"""rfcx/frugalai loading: resample to 16 kHz, cut every clip into 1 s windows.

Label convention (dataset card): label 0 = chainsaw, label 1 = environment.
The model is trained with CHAINSAW_IDX = 1 as the positive class, so the
firmware reads output[CHAINSAW_IDX] and the meaning is written into the
generated model_meta.h, not assumed. prepare_data.py prints the label
counts so the convention can be checked against the data on every machine.
"""
import hashlib
import json
import multiprocessing as mp
import os
from math import gcd

import numpy as np
from scipy.signal import resample_poly

from . import features as F

DATASET = "rfcx/frugalai"
DATASET_CHAINSAW_LABEL = 0
CHAINSAW_IDX = 1          # index of "chainsaw" in the model output
CLASS_NAMES = ["environment", "chainsaw"]
LABEL_COL = "label"
# Clips shorter than one analysis window are left out: the device always sees
# a full 1 s window, and rfcx/frugalai contains some empty (0 s) clips
# (REPORT of job 5057, 22 Nov 2026). The count is written into the report.
MIN_CLIP_S = 1.0
AUDIO_COL = "audio"


def to_target(dataset_label):
    """Dataset label -> model class index."""
    return CHAINSAW_IDX if int(dataset_label) == DATASET_CHAINSAW_LABEL else 1 - CHAINSAW_IDX


def resample(audio, sr):
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim != 1:
        raise ValueError(f"expected mono audio, got shape {audio.shape}")
    if sr == F.SAMPLE_RATE:
        return audio
    g = gcd(int(sr), F.SAMPLE_RATE)
    return resample_poly(audio, F.SAMPLE_RATE // g, int(sr) // g).astype(np.float32)


def clip_features(audio, sr):
    """One clip -> (n_windows, N_FRAMES, N_MFCC)."""
    return np.stack([F.mfcc(w) for w in F.windows(resample(audio, sr))])


def build_arrays(clips):
    """clips: iterable of (audio, sr, dataset_label).

    Returns X (windows, frames, mfcc), y (windows,), clip_id (windows,).
    clip_id keeps windows of one clip together for clip-level scoring.
    """
    X, y, cid = [], [], []
    for i, (audio, sr, label) in enumerate(clips):
        f = clip_features(audio, sr)
        X.append(f)
        y.extend([to_target(label)] * len(f))
        cid.extend([i] * len(f))
    return (np.concatenate(X).astype(np.float32),
            np.asarray(y, dtype=np.int64),
            np.asarray(cid, dtype=np.int64))


# ---------------------------------------------------------------- real data

def open_split(split, data_dir=None, revision=None):
    """A Hugging Face split, from a local copy (prepare_data.py) or the Hub."""
    if data_dir:
        from datasets import load_from_disk
        return load_from_disk(data_dir)[split]
    from datasets import load_dataset
    return load_dataset(DATASET, split=split, revision=revision)


def load_split(split, limit=None, data_dir=None):
    """Yield (audio, sr, label) one clip at a time (small runs and tests)."""
    ds = open_split(split, data_dir)
    if limit:
        ds = ds.select(range(min(limit, len(ds))))
    for s in ds:
        yield s[AUDIO_COL]["array"], s[AUDIO_COL]["sampling_rate"], s[LABEL_COL]


def _features_chunk(job):
    """Worker: features for clips [start, stop) of one split."""
    data_dir, split, start, stop, fmax = job
    F.configure(fmax=fmax)
    ds = open_split(split, data_dir).select(range(start, stop))
    X, y, n_win, info, skipped = [], [], [], [], []
    for s in ds:
        a, sr, lab = s[AUDIO_COL]["array"], s[AUDIO_COL]["sampling_rate"], s[LABEL_COL]
        info.append((int(sr), len(a)))
        if len(a) < MIN_CLIP_S * sr:
            skipped.append((int(lab), len(a) / sr))
            continue
        f = clip_features(a, sr)
        X.append(f)
        y.append(int(lab))
        n_win.append(len(f))
    Xc = (np.concatenate(X) if X else np.zeros((0, F.N_FRAMES, F.N_MFCC))).astype(np.float32)
    return Xc, y, n_win, info, skipped


def build_split(split, data_dir, limit=None, workers=1, cache_dir=None):
    """Features for a whole split, in parallel, with an on-disk cache.

    Returns X, y, cid and a summary dict (clip counts per dataset label,
    sample rates and clip lengths actually found in the data).
    """
    ds = open_split(split, data_dir)
    n = min(limit, len(ds)) if limit else len(ds)
    key = hashlib.sha1(json.dumps(
        [getattr(ds, "_fingerprint", ""), split, n, F.config(), MIN_CLIP_S], sort_keys=True).encode()).hexdigest()[:12]
    cache = os.path.join(cache_dir, f"features_{split}_{key}.npz") if cache_dir else None
    if cache and os.path.exists(cache):
        z = np.load(cache, allow_pickle=False)
        print(f"[{split}] features from cache {cache}")
        return z["X"], z["y"], z["cid"], json.loads(str(z["summary"]))

    step = max(1, min(500, -(-n // max(workers, 1))))
    jobs = [(data_dir, split, s, min(s + step, n), F.FMAX) for s in range(0, n, step)]
    print(f"[{split}] {n} clips, {len(jobs)} chunks, {workers} workers")
    if workers > 1:
        with mp.get_context("spawn").Pool(workers) as pool:
            parts = pool.map(_features_chunk, jobs)
    else:
        parts = [_features_chunk(j) for j in jobs]

    X = np.concatenate([p[0] for p in parts])
    labels = [lab for p in parts for lab in p[1]]
    n_win = [k for p in parts for k in p[2]]
    info = [i for p in parts for i in p[3]]
    skipped = [k for p in parts for k in p[4]]
    y = np.repeat([to_target(lab) for lab in labels], n_win).astype(np.int64)
    cid = np.repeat(np.arange(len(labels)), n_win).astype(np.int64)
    srs = sorted({sr for sr, _ in info})
    secs = np.array([length / sr for sr, length in info])
    summary = {
        "split": split, "clips": len(labels), "windows": int(len(y)),
        "clips_per_dataset_label": {str(k): int(v) for k, v in
                                    zip(*np.unique(labels, return_counts=True))},
        "clips_in_dataset": len(info),
        "skipped_short": {
            "min_seconds": MIN_CLIP_S, "count": len(skipped),
            "empty": sum(1 for _, sec in skipped if sec == 0),
            "per_dataset_label": {str(k): sum(1 for lab, _ in skipped if lab == k)
                                  for k in sorted({lab for lab, _ in skipped})},
        },
        "sample_rates_hz": srs,
        # Lengths of ALL clips in the split, before the short ones are left out.
        "clip_seconds": {"min": round(float(secs.min()), 3), "median": round(float(np.median(secs)), 3),
                         "max": round(float(secs.max()), 3)},
        "fingerprint": getattr(ds, "_fingerprint", None),
    }
    if cache:
        os.makedirs(cache_dir, exist_ok=True)
        np.savez(cache, X=X, y=y, cid=cid, summary=json.dumps(summary))
    return X, y, cid, summary
