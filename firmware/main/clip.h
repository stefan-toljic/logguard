// Audio clip around an alert (profile B): the last few seconds of microphone
// audio are kept in PSRAM; after an alert the device sends a 16-bit WAV clip
// so a person can listen and confirm or reject it.
// Compiled to no-ops when CONFIG_LOGGUARD_AUDIO_CLIP is off (profile A).
#pragma once

#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

// Allocates the ring buffer and the clip buffer in PSRAM.
esp_err_t clip_init(void);

// Appends n new samples (floats in [-1, 1]) from the detector task.
// When an armed clip is complete, it is handed to the alert task.
void clip_push(const float *x, size_t n);

// Called when an alert is raised: the clip will cover PRE seconds before and
// POST seconds after this moment. Ignored while a clip is already armed.
void clip_trigger(int64_t ts_us);

// Called by the alert task when it no longer needs the clip buffer.
void clip_release(void);

#ifdef __cplusplus
}
#endif
