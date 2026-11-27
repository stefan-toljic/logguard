#include "clip.h"

#include <math.h>
#include <stdbool.h>
#include <string.h>

#include "sdkconfig.h"

#if CONFIG_LOGGUARD_AUDIO_CLIP

#include "alert.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "generated/mfcc_tables.h"

static const char *TAG = "clip";

#define FS MFCC_SAMPLE_RATE
#define WAV_HEADER 44

static int16_t *s_ring;          // last s_ring_n samples, circular
static size_t s_ring_n, s_pos;
static uint64_t s_total;         // samples pushed since boot
static uint8_t *s_wav;           // header + clip, handed to the alert task
static size_t s_clip_n;          // samples in one clip
static bool s_armed;
static uint64_t s_due;           // s_total at which the clip is complete
static int64_t s_ts_us;
static volatile bool s_busy;     // alert task still sending s_wav

static void put_u32(uint8_t *p, uint32_t v)
{
    p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24;
}

static void put_u16(uint8_t *p, uint16_t v)
{
    p[0] = v; p[1] = v >> 8;
}

// Canonical 44-byte header: PCM, mono, 16 bit, FS Hz.
static void wav_header(uint8_t *h, uint32_t data_bytes)
{
    memcpy(h, "RIFF", 4);
    put_u32(h + 4, 36 + data_bytes);
    memcpy(h + 8, "WAVEfmt ", 8);
    put_u32(h + 16, 16);
    put_u16(h + 20, 1);
    put_u16(h + 22, 1);
    put_u32(h + 24, FS);
    put_u32(h + 28, FS * 2);
    put_u16(h + 32, 2);
    put_u16(h + 34, 16);
    memcpy(h + 36, "data", 4);
    put_u32(h + 40, data_bytes);
}

esp_err_t clip_init(void)
{
    s_clip_n = (size_t)(CONFIG_LOGGUARD_CLIP_PRE_S + CONFIG_LOGGUARD_CLIP_POST_S) * FS;
    s_ring_n = s_clip_n + FS;    // 1 s margin: a clip is cut up to 0.5 s late
    s_ring = heap_caps_calloc(s_ring_n, sizeof(int16_t), MALLOC_CAP_SPIRAM);
    s_wav = heap_caps_malloc(WAV_HEADER + s_clip_n * sizeof(int16_t), MALLOC_CAP_SPIRAM);
    if (!s_ring || !s_wav) {
        ESP_LOGE(TAG, "no PSRAM for the audio clip");
        return ESP_ERR_NO_MEM;
    }
    ESP_LOGI(TAG, "audio clip on: %d s before + %d s after an alert, %u bytes",
             CONFIG_LOGGUARD_CLIP_PRE_S, CONFIG_LOGGUARD_CLIP_POST_S,
             (unsigned)(WAV_HEADER + s_clip_n * sizeof(int16_t)));
    return ESP_OK;
}

static void cut_clip(void)
{
    if (s_busy) {
        ESP_LOGW(TAG, "previous clip still sending, this one is dropped");
        return;
    }
    size_t start = (s_pos + s_ring_n - s_clip_n) % s_ring_n;
    size_t first = s_ring_n - start < s_clip_n ? s_ring_n - start : s_clip_n;
    uint8_t *pcm = s_wav + WAV_HEADER;
    memcpy(pcm, s_ring + start, first * sizeof(int16_t));
    memcpy(pcm + first * sizeof(int16_t), s_ring, (s_clip_n - first) * sizeof(int16_t));
    wav_header(s_wav, s_clip_n * sizeof(int16_t));
    s_busy = true;
    alert_post_clip(s_wav, WAV_HEADER + s_clip_n * sizeof(int16_t), s_ts_us);
}

void clip_push(const float *x, size_t n)
{
    if (!s_ring) return;
    for (size_t i = 0; i < n; i++) {
        float v = x[i] * 32767.0f;
        s_ring[s_pos] = (int16_t)lrintf(v > 32767.0f ? 32767.0f : (v < -32768.0f ? -32768.0f : v));
        if (++s_pos == s_ring_n) s_pos = 0;
    }
    s_total += n;
    if (s_armed && s_total >= s_due) {
        s_armed = false;
        cut_clip();
    }
}

void clip_trigger(int64_t ts_us)
{
    if (!s_ring || s_armed) return;
    s_armed = true;
    s_due = s_total + (uint64_t)CONFIG_LOGGUARD_CLIP_POST_S * FS;
    s_ts_us = ts_us;
}

void clip_release(void)
{
    s_busy = false;
}

#else  // profile A: no audio leaves the device

esp_err_t clip_init(void) { return ESP_OK; }
void clip_push(const float *x, size_t n) { (void)x; (void)n; }
void clip_trigger(int64_t ts_us) { (void)ts_us; }
void clip_release(void) {}

#endif
