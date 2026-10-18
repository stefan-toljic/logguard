// MFCC front end, a line-by-line port of training/logguard/features.py.
// Plain C with its own FFT so the same file builds on the host for the
// parity test (firmware/host_test) and on the ESP32-S3.
#pragma once

#include "generated/mfcc_tables.h"

#ifdef __cplusplus
extern "C" {
#endif

void mfcc_init(void);

// pcm: MFCC_WIN_SAMPLES floats in [-1, 1]
// out: MFCC_N_FRAMES * MFCC_N_MFCC floats, frame-major (same as numpy)
void mfcc_compute(const float *pcm, float *out);

#ifdef __cplusplus
}
#endif
