"""Train the DS-CNN chainsaw detector on rfcx/frugalai.

    python prepare_data.py --out data/frugalai                     # once, needs internet
    python train.py --data-dir data/frugalai --out runs/ds_cnn     # no network needed
    python train.py --out runs/smoke --synthetic                   # plumbing check only

Writes into --out:
  model.keras           trained float model
  norm.npz              per-coefficient mean/std (training windows only)
  data.npz              INT8 calibration windows + test windows for export.py
  run_config.json       every setting, feature config, data summary, versions
  history.json          loss/accuracy per epoch
  train_metrics.json    float metrics on validation and test
"""
import argparse
import json
import os
import platform
import sys
import time

import numpy as np

from logguard import dataset as D
from logguard import features as F
from logguard import metrics, synthetic


def split_by_clip(cid, val_frac, seed):
    """Validation is a set of whole clips, so no clip has windows on both sides."""
    clips = np.unique(cid)
    rng = np.random.default_rng(seed)
    rng.shuffle(clips)
    val = set(clips[: int(len(clips) * val_frac)])
    is_val = np.array([c in val for c in cid])
    return ~is_val, is_val


def versions():
    out = {"python": sys.version.split()[0], "platform": platform.platform(), "numpy": np.__version__}
    for mod in ("tensorflow", "scipy", "datasets"):
        try:
            out[mod] = __import__(mod).__version__
        except Exception:  # noqa: BLE001  (optional modules)
            out[mod] = None
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--data-dir", default=None, help="copy written by prepare_data.py (else: Hub)")
    p.add_argument("--train-split", default="train")
    p.add_argument("--test-split", default="test")
    p.add_argument("--epochs", type=int, default=40)
    p.add_argument("--batch", type=int, default=64)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--patience", type=int, default=6)
    p.add_argument("--val-frac", type=float, default=0.2)
    p.add_argument("--filters", type=int, default=32)
    p.add_argument("--blocks", type=int, default=4)
    p.add_argument("--fmax", type=float, default=F.FMAX, help="mel upper edge in Hz")
    p.add_argument("--limit", type=int, default=None, help="max clips per split (smoke runs)")
    p.add_argument("--workers", type=int, default=int(os.environ.get("SLURM_CPUS_PER_TASK", 1)))
    p.add_argument("--cache-dir", default=None, help="feature cache (default: <data-dir>/cache)")
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    F.configure(fmax=a.fmax)
    t_start = time.time()

    # Features first, TensorFlow later: worker processes stay light.
    if a.synthetic:
        n = a.limit or 200
        X, y, cid = D.build_arrays(synthetic.clips(n, seed=a.seed))
        Xt, yt, cidt = D.build_arrays(synthetic.clips(max(n // 4, 20), seed=a.seed + 1))
        data_summary = {"source": "SINTETIČKI klipovi (samo provjera koda, bez stvarnog značenja)"}
    elif a.data_dir:
        cache = a.cache_dir or os.path.join(a.data_dir, "cache")
        X, y, cid, s_tr = D.build_split(a.train_split, a.data_dir, a.limit, a.workers, cache)
        Xt, yt, cidt, s_te = D.build_split(a.test_split, a.data_dir, a.limit, a.workers, cache)
        source = D.DATASET
        if os.path.exists(os.path.join(a.data_dir, synthetic.FAKE_MARKER)):
            source = "SINTETIČKI zamjenski podaci (nisu rfcx/frugalai, samo provjera koda)"
        data_summary = {"source": source, "data_dir": os.path.abspath(a.data_dir),
                        "train": s_tr, "test": s_te}
    else:
        X, y, cid = D.build_arrays(D.load_split(a.train_split, a.limit))
        Xt, yt, cidt = D.build_arrays(D.load_split(a.test_split, a.limit))
        data_summary = {"source": D.DATASET + " (Hub, streamed)"}
    t_feat = time.time() - t_start

    tr, va = split_by_clip(cid, a.val_frac, a.seed)
    print(f"windows: train {tr.sum()}  val {va.sum()}  test {len(yt)}  "
          f"chainsaw share train {y[tr].mean():.3f} test {yt.mean():.3f}  "
          f"(features {t_feat:.0f} s)")

    import tensorflow as tf
    from logguard import model as M
    tf.keras.utils.set_random_seed(a.seed)

    mean = X[tr].mean(axis=(0, 1))
    std = X[tr].std(axis=(0, 1)) + 1e-6
    norm = lambda z: ((z - mean) / std)[..., np.newaxis]  # noqa: E731

    counts = np.bincount(y[tr], minlength=2)
    class_weight = {c: len(y[tr]) / (2.0 * max(counts[c], 1)) for c in range(2)}

    model = M.build(n_filters=a.filters, n_blocks=a.blocks)
    model.summary(print_fn=print)
    model.compile(optimizer=tf.keras.optimizers.Adam(a.lr),
                  loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    hist = model.fit(norm(X[tr]), y[tr], validation_data=(norm(X[va]), y[va]),
                     epochs=a.epochs, batch_size=a.batch, class_weight=class_weight,
                     callbacks=[tf.keras.callbacks.EarlyStopping(
                         patience=a.patience, restore_best_weights=True, monitor="val_loss")],
                     verbose=2)

    pv = model.predict(norm(X[va]), verbose=0)[:, D.CHAINSAW_IDX]
    pt = model.predict(norm(Xt), verbose=0)[:, D.CHAINSAW_IDX]
    train_metrics = {"val_float": metrics.report(y[va], pv, cid[va]),
                     "test_float": metrics.report(yt, pt, cidt)}
    print("val  (float):", train_metrics["val_float"])
    print("test (float):", train_metrics["test_float"])

    model.save(os.path.join(a.out, "model.keras"))
    np.savez(os.path.join(a.out, "norm.npz"), mean=mean, std=std)
    # Representative windows for INT8 calibration come from training data,
    # balanced across classes; test windows are kept for the float/INT8 check.
    rng = np.random.default_rng(a.seed)
    rep = np.concatenate([rng.permutation(np.where(y[tr] == c)[0])[:250] for c in (0, 1)])
    np.savez_compressed(os.path.join(a.out, "data.npz"),
                        rep=X[tr][rep], Xt=Xt, yt=yt, cidt=cidt,
                        Xv=X[va], yv=y[va], cidv=cid[va])

    config = {
        "args": vars(a),
        "features": F.config(),
        "labels": {"dataset_chainsaw_label": D.DATASET_CHAINSAW_LABEL,
                   "model_chainsaw_idx": D.CHAINSAW_IDX, "class_names": D.CLASS_NAMES},
        "split": {"val": "whole clips from the train split, val_frac of them",
                  "window_label": "every window gets the label of its clip",
                  "test": f"dataset split '{a.test_split}', never seen in training"},
        "windows": {"train": int(tr.sum()), "val": int(va.sum()), "test": int(len(yt)),
                    "chainsaw_share_train": float(y[tr].mean()), "chainsaw_share_test": float(yt.mean())},
        "class_weight": {D.CLASS_NAMES[k]: float(v) for k, v in class_weight.items()},
        "epochs_run": len(hist.history["loss"]),
        "data": data_summary,
        "versions": versions(),
        "host": platform.node(),
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "seconds": {"features": round(t_feat), "total": round(time.time() - t_start)},
        "params": int(model.count_params()),
    }
    with open(os.path.join(a.out, "run_config.json"), "w") as f:
        json.dump(config, f, indent=2, default=str)
    with open(os.path.join(a.out, "history.json"), "w") as f:
        json.dump({k: [float(v) for v in vs] for k, vs in hist.history.items()}, f, indent=2)
    with open(os.path.join(a.out, "train_metrics.json"), "w") as f:
        json.dump(train_metrics, f, indent=2)
    print(f"done in {time.time() - t_start:.0f} s, wrote {os.path.abspath(a.out)}")


if __name__ == "__main__":
    main()
