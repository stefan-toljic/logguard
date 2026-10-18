"""Train the DS-CNN chainsaw detector on rfcx/frugalai.

    python train.py --out runs/ds_cnn            # real data (needs `datasets`)
    python train.py --out runs/smoke --synthetic # quick check without download

Writes model.keras, norm.npz (per-coefficient mean/std) and data.npz
(test windows used later by export.py).
"""
import argparse
import os

import numpy as np

from logguard import dataset as D
from logguard import model as M
from logguard import metrics, synthetic


def split_by_clip(cid, val_frac, seed):
    clips = np.unique(cid)
    rng = np.random.default_rng(seed)
    rng.shuffle(clips)
    val = set(clips[: int(len(clips) * val_frac)])
    is_val = np.array([c in val for c in cid])
    return ~is_val, is_val


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--epochs", type=int, default=40)
    p.add_argument("--batch", type=int, default=64)
    p.add_argument("--limit", type=int, default=None, help="max clips per split")
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)

    import tensorflow as tf
    tf.keras.utils.set_random_seed(a.seed)

    if a.synthetic:
        n = a.limit or 200
        train_clips = synthetic.clips(n, seed=a.seed)
        test_clips = synthetic.clips(max(n // 4, 20), seed=a.seed + 1)
    else:
        train_clips = D.load_split("train", a.limit)
        test_clips = D.load_split("test", a.limit)

    X, y, cid = D.build_arrays(train_clips)
    Xt, yt, cidt = D.build_arrays(test_clips)
    tr, va = split_by_clip(cid, 0.2, a.seed)
    print(f"windows: train {tr.sum()}  val {va.sum()}  test {len(yt)}  "
          f"chainsaw share {y.mean():.2f}")

    mean = X[tr].mean(axis=(0, 1))
    std = X[tr].std(axis=(0, 1)) + 1e-6
    norm = lambda z: ((z - mean) / std)[..., np.newaxis]

    counts = np.bincount(y[tr], minlength=2)
    class_weight = {c: len(y[tr]) / (2.0 * max(counts[c], 1)) for c in range(2)}

    model = M.build()
    model.compile(optimizer=tf.keras.optimizers.Adam(1e-3),
                  loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    model.fit(norm(X[tr]), y[tr], validation_data=(norm(X[va]), y[va]),
              epochs=a.epochs, batch_size=a.batch, class_weight=class_weight,
              callbacks=[tf.keras.callbacks.EarlyStopping(
                  patience=6, restore_best_weights=True, monitor="val_loss")],
              verbose=2)

    probs = model.predict(norm(Xt), verbose=0)[:, D.CHAINSAW_IDX]
    print("test (float):", metrics.report(yt, probs, cidt))

    model.save(os.path.join(a.out, "model.keras"))
    np.savez(os.path.join(a.out, "norm.npz"), mean=mean, std=std)
    # Representative windows for INT8 calibration come from training data,
    # balanced across classes; test windows are kept for the float/INT8 check.
    rng = np.random.default_rng(a.seed)
    rep = np.concatenate([rng.permutation(np.where(y[tr] == c)[0])[:250] for c in (0, 1)])
    np.savez_compressed(os.path.join(a.out, "data.npz"),
                        rep=X[tr][rep], Xt=Xt, yt=yt, cidt=cidt)


if __name__ == "__main__":
    main()
