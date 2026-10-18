import os
import re
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from logguard import dataset as D  # noqa: E402
from logguard import features as F  # noqa: E402


def test_label_mapping_chainsaw_is_positive():
    # rfcx/frugalai: label 0 = chainsaw. The firmware alarms on output[CHAINSAW_IDX].
    assert D.to_target(0) == D.CHAINSAW_IDX
    assert D.to_target(1) != D.CHAINSAW_IDX
    assert D.CLASS_NAMES[D.CHAINSAW_IDX] == "chainsaw"


def test_whole_clip_is_used_not_just_first_second():
    clip = np.zeros(3 * F.SAMPLE_RATE, dtype=np.float32)
    clip[-F.SAMPLE_RATE:] = 1.0                      # event only in the last second
    wins = F.windows(clip)
    assert len(wins) == 5                            # 0, 0.5, 1, 1.5, 2 s
    assert wins[-1].min() == 1.0


def test_resample_12k_to_16k():
    x = np.random.default_rng(0).normal(size=3 * 12000).astype(np.float32)
    assert len(D.resample(x, 12000)) == 3 * F.SAMPLE_RATE


def test_mfcc_shape_and_reference():
    rng = np.random.default_rng(0)
    w = rng.normal(0, 0.1, F.WIN_SAMPLES).astype(np.float32)
    m = F.mfcc(w)
    assert m.shape == (F.N_FRAMES, F.N_MFCC) == (49, 40)
    # Independent reference for frame 7 with scipy's window and a naive DFT.
    from scipy.signal import get_window
    frame = w[7 * F.HOP: 7 * F.HOP + F.N_FFT] * get_window("hann", F.N_FFT)
    n = np.arange(F.N_FFT)
    k = np.arange(F.N_BINS)[:, None]
    spec = (frame * np.exp(-2j * np.pi * k * n / F.N_FFT)).sum(axis=1)
    ref = F.dct_matrix() @ np.log(F.mel_filterbank() @ np.abs(spec) ** 2 + F.LOG_EPS)
    np.testing.assert_allclose(m[7], ref, rtol=1e-3, atol=1e-2)


def test_mel_filters_cover_band():
    fb = F.mel_filterbank()
    assert fb.shape == (F.N_MELS, F.N_BINS)
    assert (fb.sum(axis=1) > 0).all()


def test_firmware_registers_every_export_op():
    import export
    src = open(os.path.join(os.path.dirname(__file__), "..", "..", "firmware", "main", "detector.cc")).read()
    registered = set(re.findall(r"resolver\.Add(\w+)\(\)", src))
    tfl_to_add = {"CONV_2D": "Conv2D", "DEPTHWISE_CONV_2D": "DepthwiseConv2D",
                  "FULLY_CONNECTED": "FullyConnected", "SOFTMAX": "Softmax", "MEAN": "Mean",
                  "RESHAPE": "Reshape", "AVERAGE_POOL_2D": "AveragePool2D",
                  "QUANTIZE": "Quantize", "DEQUANTIZE": "Dequantize"}
    assert {tfl_to_add[o] for o in export.FIRMWARE_OPS} == registered


@pytest.mark.slow
def test_train_and_export_smoke(tmp_path):
    pytest.importorskip("tensorflow")
    import export
    import train
    run, gen = tmp_path / "run", tmp_path / "gen"
    train.main(["--out", str(run), "--synthetic", "--limit", "80", "--epochs", "12"])
    export.main(["--run", str(run), "--gen-dir", str(gen)])
    meta = (gen / "model_meta.h").read_text()
    assert "#define MODEL_CHAINSAW_IDX 1" in meta
    assert (run / "chainsaw.tflite").stat().st_size < 40 * 1024
    for name in ("model_data.cc", "mfcc_tables.h", "selftest_vectors.h"):
        assert (gen / name).exists()
