"""rfcx/frugalai loading: resample to 16 kHz, cut every clip into 1 s windows.

Label convention (dataset card): label 0 = chainsaw, label 1 = environment.
The model is trained with CHAINSAW_IDX = 1 as the positive class, so the
firmware reads output[CHAINSAW_IDX] and the meaning is written into the
generated model_meta.h, not assumed.
"""
from math import gcd

import numpy as np
from scipy.signal import resample_poly

from . import features as F

DATASET = "rfcx/frugalai"
DATASET_CHAINSAW_LABEL = 0
CHAINSAW_IDX = 1          # index of "chainsaw" in the model output
CLASS_NAMES = ["environment", "chainsaw"]


def to_target(dataset_label):
    """Dataset label -> model class index."""
    return CHAINSAW_IDX if int(dataset_label) == DATASET_CHAINSAW_LABEL else 1 - CHAINSAW_IDX


def resample(audio, sr):
    audio = np.asarray(audio, dtype=np.float32)
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


def load_split(split, limit=None):
    """Yield (audio, sr, label) from the Hugging Face dataset."""
    from datasets import load_dataset  # optional dependency, only for real data
    ds = load_dataset(DATASET, split=split)
    if limit:
        ds = ds.select(range(min(limit, len(ds))))
    for s in ds:
        yield s["audio"]["array"], s["audio"]["sampling_rate"], s["label"]
