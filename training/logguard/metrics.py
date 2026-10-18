"""Window- and clip-level scores."""
import numpy as np


def f1(y, pred):
    tp = np.sum((pred == 1) & (y == 1))
    fp = np.sum((pred == 1) & (y == 0))
    fn = np.sum((pred == 0) & (y == 1))
    return 2 * tp / max(2 * tp + fp + fn, 1)


def clip_level(y, probs, cid):
    """A clip counts as chainsaw if any of its windows does (max pooling)."""
    ids = np.unique(cid)
    yc = np.array([y[cid == i][0] for i in ids])
    pc = np.array([probs[cid == i].max() for i in ids])
    return yc, pc


def report(y, probs, cid, threshold=0.5):
    pred = (probs >= threshold).astype(int)
    yc, pc = clip_level(y, probs, cid)
    return {
        "window_acc": float(np.mean(pred == y)),
        "window_f1": float(f1(y, pred)),
        "clip_f1": float(f1(yc, (pc >= threshold).astype(int))),
    }
