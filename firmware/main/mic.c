#include "mic.h"

#include <math.h>

#include "driver/i2s_std.h"
#include "esp_check.h"
#include "freertos/FreeRTOS.h"
#include "sdkconfig.h"

#include "generated/mfcc_tables.h"

static const char *TAG = "mic";
static i2s_chan_handle_t s_rx;
static float s_gain;

#define CHUNK 256

esp_err_t mic_init(void)
{
    // 8 x 512 frames of DMA = 256 ms, enough to cover MFCC + inference.
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    chan_cfg.dma_desc_num = 8;
    chan_cfg.dma_frame_num = 512;
    ESP_RETURN_ON_ERROR(i2s_new_channel(&chan_cfg, NULL, &s_rx), TAG, "new channel");

    i2s_std_config_t std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(MFCC_SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = CONFIG_LOGGUARD_I2S_BCLK,
            .ws = CONFIG_LOGGUARD_I2S_WS,
            .dout = I2S_GPIO_UNUSED,
            .din = CONFIG_LOGGUARD_I2S_DIN,
        },
    };
    std_cfg.slot_cfg.slot_mask = I2S_STD_SLOT_LEFT;
    ESP_RETURN_ON_ERROR(i2s_channel_init_std_mode(s_rx, &std_cfg), TAG, "std mode");
    ESP_RETURN_ON_ERROR(i2s_channel_enable(s_rx), TAG, "enable");

    s_gain = powf(10.0f, CONFIG_LOGGUARD_MIC_GAIN_DB / 20.0f);
    return ESP_OK;
}

esp_err_t mic_read(float *out, size_t n)
{
    // INMP441 sends 24-bit samples left-aligned in 32-bit slots.
    static int32_t raw[CHUNK];
    const float scale = s_gain / 2147483648.0f;
    size_t done = 0;
    while (done < n) {
        size_t want = n - done < CHUNK ? n - done : CHUNK;
        size_t got = 0;
        ESP_RETURN_ON_ERROR(i2s_channel_read(s_rx, raw, want * sizeof(int32_t), &got, portMAX_DELAY),
                            TAG, "read");
        size_t k = got / sizeof(int32_t);
        for (size_t i = 0; i < k; i++) {
            float v = raw[i] * scale;
            out[done + i] = v > 1.0f ? 1.0f : (v < -1.0f ? -1.0f : v);
        }
        done += k;
    }
    return ESP_OK;
}
