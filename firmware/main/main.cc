// LogGuard PoC 1: ESP32-S3 + INMP441, chainsaw detection, Wi-Fi MQTT alerts.
#include <string.h>

#include "esp_attr.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "sdkconfig.h"

#include "alert.h"
#include "detector.h"
#include "generated/mfcc_tables.h"
#include "mic.h"

static const char *TAG = "logguard";

// 1 s window, advanced by 0.5 s: the same windows the model was trained on.
// Kept in PSRAM so internal RAM stays free for the tensor arena and Wi-Fi.
EXT_RAM_BSS_ATTR static float s_window[MFCC_WIN_SAMPLES];

static void detector_task(void *arg)
{
    const float threshold = CONFIG_LOGGUARD_THRESHOLD_PCT / 100.0f;
    const int64_t cooldown_us = (int64_t)CONFIG_LOGGUARD_COOLDOWN_S * 1000000;
    int consec = 0;
    int64_t quiet_until = 0;

    ESP_ERROR_CHECK(mic_read(s_window, MFCC_WIN_SAMPLES));
    for (;;) {
        detection_t d;
        if (detector_run(s_window, &d) != ESP_OK) {
            ESP_LOGE(TAG, "inference failed");
        } else {
            int64_t now = alert_now_us();
            consec = d.chainsaw_prob >= threshold ? consec + 1 : 0;
#if CONFIG_LOGGUARD_LOG_SCORES
            ESP_LOGI(TAG, "p=%.2f raw=%d/%d consec=%d mfcc=%lums inf=%lums", d.chainsaw_prob,
                     d.raw[0], d.raw[1], consec, (unsigned long)(d.mfcc_us / 1000),
                     (unsigned long)(d.invoke_us / 1000));
#endif
            if (consec >= CONFIG_LOGGUARD_CONSEC_NEEDED && now >= quiet_until) {
                alert_t a = {.score = d.chainsaw_prob, .raw = d.chainsaw_raw,
                             .ts_us = now, .windows = (uint32_t)consec};
                alert_post(&a);
                quiet_until = now + cooldown_us;
                consec = 0;
            }
        }
        // Keep listening during the cooldown, so the DMA buffer never overflows.
        memmove(s_window, s_window + MFCC_HOP_WINDOW,
                (MFCC_WIN_SAMPLES - MFCC_HOP_WINDOW) * sizeof(float));
        ESP_ERROR_CHECK(mic_read(s_window + MFCC_WIN_SAMPLES - MFCC_HOP_WINDOW, MFCC_HOP_WINDOW));
    }
}

extern "C" void app_main(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    ESP_ERROR_CHECK(detector_init());
#if CONFIG_LOGGUARD_SELFTEST
    ESP_LOGI(TAG, "T1 self-test: %s", detector_selftest() ? "PASS" : "FAIL");
#endif
    ESP_ERROR_CHECK(mic_init());
    ESP_ERROR_CHECK(alert_init());

    xTaskCreatePinnedToCore(detector_task, "detector", 8192, NULL, 5, NULL, 1);
}
