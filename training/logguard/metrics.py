"""Window-, clip- and alarm-level scores.

Window: one 1 s MFCC window, exactly what the model sees.
Clip:   a dataset clip counts as chainsaw if any of its windows does.
Alarm:  the firmware rule from firmware/main/main.cc: an alert needs
        CONSEC windows in a row at or above the threshold.
"""
import numpy as np

WINDOWS_PER_HOUR = 2 * 3600          # one window every 0.5 s


def f1(y, pred):
    tp = np.sum((pred == 1) & (y == 1))
    fp = np.sum((pred == 1) & (y == 0))
    fn = np.sum((pred == 0) & (y == 1))
    return 2 * tp / max(2 * tp + fp + fn, 1)


def confusion(y, pred):
    return {"tp": int(np.sum((pred == 1) & (y == 1))), "fp": int(np.sum((pred == 1) & (y == 0))),
            "fn": int(np.sum((pred == 0) & (y == 1))), "tn": int(np.sum((pred == 0) & (y == 0)))}


def scores(y, pred):
    c = confusion(y, pred)
    tp, fp, fn, tn = c["tp"], c["fp"], c["fn"], c["tn"]
    return {"n": int(len(y)), "acc": float(np.mean(pred == y)) if len(y) else 0.0,
            "precision": tp / max(tp + fp, 1), "recall": tp / max(tp + fn, 1),
            "f1": float(f1(y, pred)), "fpr": fp / max(fp + tn, 1), **c}


def clip_level(y, probs, cid):
    """A clip counts as chainsaw if any of its windows does (max pooling)."""
    ids = np.unique(cid)
    yc = np.array([y[cid == i][0] for i in ids])
    pc = np.array([probs[cid == i].max() for i in ids])
    return yc, pc


def alarm_level(y, probs, cid, threshold, consec):
    """Firmware rule per clip: alert if `consec` windows in a row >= threshold."""
    ids = np.unique(cid)
    yc, fired = [], []
    for i in ids:
        m = cid == i
        run = best = 0
        for p in probs[m]:
            run = run + 1 if p >= threshold else 0
            best = max(best, run)
        yc.append(y[m][0])
        fired.append(int(best >= consec))
    return np.array(yc), np.array(fired)


def report(y, probs, cid, threshold=0.5):
    """Short form used during training (kept for train.py and tests)."""
    pred = (probs >= threshold).astype(int)
    yc, pc = clip_level(y, probs, cid)
    return {
        "window_acc": float(np.mean(pred == y)),
        "window_f1": float(f1(y, pred)),
        "clip_f1": float(f1(yc, (pc >= threshold).astype(int))),
    }


def full_report(y, probs, cid, threshold, consec):
    """Everything export.py writes into report.json / REPORT.md."""
    pred = (probs >= threshold).astype(int)
    yc, pc = clip_level(y, probs, cid)
    ya, fired = alarm_level(y, probs, cid, threshold, consec)
    win = scores(y, pred)
    neg_windows = max(int(np.sum(y == 0)), 1)
    sweep = []
    for t in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95):
        p = (probs >= t).astype(int)
        s = scores(y, p)
        sweep.append({"threshold": t, "precision": round(s["precision"], 4),
                      "recall": round(s["recall"], 4), "f1": round(s["f1"], 4),
                      "fpr": round(s["fpr"], 5)})
    return {
        "threshold": threshold, "consec": consec,
        "window": win,
        "clip": scores(yc, (pc >= threshold).astype(int)),
        "alarm": scores(ya, fired),
        # Upper bound for the device: every false window on non-chainsaw audio,
        # before the consecutive-window rule and the cooldown remove most of them.
        "false_windows_per_hour": win["fp"] / neg_windows * WINDOWS_PER_HOUR,
        "sweep": sweep,
    }
