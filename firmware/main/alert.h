// Alert path for PoC 1: Wi-Fi + MQTT (QoS 1) to the laptop broker.
// Replaces the LTE/SMS alert_send from the Phase 5 draft.
#pragma once

#include <stdint.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    float score;        // chainsaw probability 0..1
    int8_t raw;         // raw INT8 output for the chainsaw class
    int64_t ts_us;      // detection time, epoch microseconds if time_synced
    uint32_t windows;   // consecutive windows that triggered the alert
} alert_t;

// Starts Wi-Fi, syncs the clock (SNTP), starts the alert task.
esp_err_t alert_init(void);

// Queue an alert; never blocks the audio path.
void alert_post(const alert_t *a);

// Current time in epoch microseconds (or since boot if not synced).
int64_t alert_now_us(void);

#ifdef __cplusplus
}
#endif
