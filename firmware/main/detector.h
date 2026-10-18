// MFCC + INT8 DS-CNN inference on one 1 s window.
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    float chainsaw_prob;   // dequantized output[MODEL_CHAINSAW_IDX]
    int8_t chainsaw_raw;   // raw INT8 output[MODEL_CHAINSAW_IDX]
    int8_t raw[2];         // raw INT8 outputs, as the Python interpreter reports them
    uint32_t mfcc_us;
    uint32_t invoke_us;
} detection_t;

esp_err_t detector_init(void);

// pcm: MFCC_WIN_SAMPLES floats in [-1, 1]
esp_err_t detector_run(const float *pcm, detection_t *out);

// Test T1: C MFCC vs. Python and ESP32 model output vs. Python interpreter
// on the vectors in generated/selftest_vectors.h. Returns true on pass.
bool detector_selftest(void);

#ifdef __cplusplus
}
#endif
