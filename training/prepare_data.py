"""Download rfcx/frugalai once and check it before any training.

    python prepare_data.py --out data/frugalai

Run this where there is internet (on the cluster: the login node, or the
laptop followed by scp). Training jobs then read the local copy with
`--data-dir data/frugalai` and need no network.

Writes:
  <out>/                 the dataset (datasets.save_to_disk)
  <out>/data_summary.json clip counts per label, sample rates, clip lengths
                          and the spectrum check below

Spectrum check: average power spectrum of a sample of clips per label after
resampling to 16 kHz, as share of energy above 5, 6 and 7 kHz. It shows
where the data stops, which decides the mel FMAX (features.FMAX).
"""
import argparse
import json
import os
import sys

import numpy as np
from scipy.signal import welch

from logguard import dataset as D
from logguard import features as F
from logguard.synthetic import FAKE_MARKER


def spectrum_check(ds, per_label, seed):
    rng = np.random.default_rng(seed)
    labels = np.asarray(ds[D.LABEL_COL])
    out = {}
    for lab in sorted(set(labels.tolist())):
        idx = rng.permutation(np.where(labels == lab)[0])[:per_label]
        acc = None
        for i in idx:
            s = ds[int(i)][D.AUDIO_COL]
            x = D.resample(s["array"], s["sampling_rate"])
            f, p = welch(x, fs=F.SAMPLE_RATE, nperseg=1024)
            acc = p if acc is None else acc + p
        total = acc.sum()
        out[str(lab)] = {
            "clips": int(len(idx)),
            **{f"energy_above_{k}k": float(acc[f >= k * 1000].sum() / total) for k in (5, 6, 7)},
        }
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--revision", default=None, help="Hub revision (commit) to pin, optional")
    p.add_argument("--spectrum-clips", type=int, default=200, help="per label, 0 = skip")
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args(argv)

    from datasets import load_dataset, load_from_disk
    if os.path.exists(os.path.join(a.out, "dataset_dict.json")):
        print(f"using existing copy in {a.out}")
        dd, reused = load_from_disk(a.out), True
    else:
        reused = False
        dd = load_dataset(D.DATASET, revision=a.revision)
        dd.save_to_disk(a.out)
        dd = load_from_disk(a.out)
    print(dd)

    if os.path.exists(os.path.join(a.out, FAKE_MARKER)):
        source = "SYNTHETIC stand-in (not real data)"
    elif reused:
        source = D.DATASET + " (existing local copy)"
    else:
        source = D.DATASET
    summary = {"dataset": source, "revision": a.revision, "splits": {}}
    for split, ds in dd.items():
        cols = ds.column_names
        if D.LABEL_COL not in cols or D.AUDIO_COL not in cols:
            sys.exit(f"split {split}: expected columns '{D.AUDIO_COL}' and '{D.LABEL_COL}', got {cols}")
        labels = np.asarray(ds[D.LABEL_COL])
        feat = ds.features[D.LABEL_COL]
        names = getattr(feat, "names", None)
        # Sample rate and length from a sample of clips (decoding all is slow).
        rng = np.random.default_rng(a.seed)
        srs, secs = set(), []
        for i in rng.permutation(len(ds))[:300]:
            s = ds[int(i)][D.AUDIO_COL]
            srs.add(int(s["sampling_rate"]))
            secs.append(len(s["array"]) / s["sampling_rate"])
        summary["splits"][split] = {
            "clips": len(ds),
            "clips_per_label": {str(k): int(v) for k, v in zip(*np.unique(labels, return_counts=True))},
            "label_names": names,
            "sample_rates_hz_sampled": sorted(srs),
            "clip_seconds_sampled": {"min": round(min(secs), 3), "median": round(float(np.median(secs)), 3),
                                     "max": round(max(secs), 3)},
            "fingerprint": ds._fingerprint,
        }
        if names and names[D.DATASET_CHAINSAW_LABEL].lower() != "chainsaw":
            print(f"WARNING: label {D.DATASET_CHAINSAW_LABEL} is named '{names[D.DATASET_CHAINSAW_LABEL]}', "
                  "not 'chainsaw'. Check DATASET_CHAINSAW_LABEL in logguard/dataset.py before training.")
    if a.spectrum_clips:
        summary["spectrum_train_16k"] = spectrum_check(dd["train"], a.spectrum_clips, a.seed)

    with open(os.path.join(a.out, "data_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
