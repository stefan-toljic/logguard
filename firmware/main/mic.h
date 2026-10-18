// INMP441 on I2S0, 16 kHz mono (L/R pin to GND = left slot).
#pragma once

#include <stddef.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t mic_init(void);

// Blocks until n samples are read; writes floats in [-1, 1] with gain applied.
esp_err_t mic_read(float *out, size_t n);

#ifdef __cplusplus
}
#endif
