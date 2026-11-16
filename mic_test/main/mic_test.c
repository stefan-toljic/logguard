// LogGuard: stand-alone INMP441 check on the ESP32-S3.
//
// Uses the same I2S settings as firmware/main/mic.c (I2S0 master, Philips,
// 32-bit slots, 16 kHz, pins 4/5/6), but reads BOTH slots so the log shows
// which slot the microphone actually sends in. Prints DC, RMS and peak per
// slot, and on request ('w' over the serial port) records a short 16-bit WAV
// and sends it as base64 (see tools/capture_wav.py).

#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "driver/gpio.h"
#include "driver/i2s_std.h"
#include "driver/uart.h"
#include "esp_err.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

static const char *TAG = "mic_test";

#define FS       CONFIG_MICTEST_SAMPLE_RATE
#define CHUNK    256                       // stereo frames per read
// The 24-bit word sits in the top 24 bits of the 32-bit slot, so full scale
// is (2^23 - 1) * 256, which is 2^31 to within 1e-6 dB.
#define FULL     2147483648.0
// Datasheet DS-INMP441-00 rev 1.1, p. 10: output is zero for the first 2^18
// SCK cycles after power-up. With SCK = 64 x fs that is 2^18 / 64 = 4096
// frames at any sample rate (256 ms at 16 kHz).
#define STARTUP_FRAMES 4096
#define CONSOLE  CONFIG_ESP_CONSOLE_UART_NUM

static i2s_chan_handle_t s_rx;
static int32_t s_buf[CHUNK * 2];           // interleaved L, R

typedef struct {
    double sum, sum2;
    int64_t peak;
    uint32_t n, lsb_nonzero, zeros;
    int32_t first, min, max;
} slot_stats_t;

static void stats_reset(slot_stats_t *s)
{
    memset(s, 0, sizeof(*s));
    s->min = INT32_MAX;
    s->max = INT32_MIN;
}

static void stats_add(slot_stats_t *s, int32_t v)
{
    if (s->n == 0) s->first = v;
    s->n++;
    s->sum += v;
    s->sum2 += (double)v * v;
    int64_t a = v < 0 ? -(int64_t)v : v;
    if (a > s->peak) s->peak = a;
    if (v < s->min) s->min = v;
    if (v > s->max) s->max = v;
    if (v & 0xFF) s->lsb_nonzero++;   // INMP441 sends 24 bits: the low byte should stay 0
    if (v == 0) s->zeros++;
}

// Peak level: 0 dBFS = a sample at full scale.
static double peak_dbfs(double x)
{
    return x <= 0.0 ? -200.0 : 20.0 * log10(x / FULL);
}

// RMS level in the datasheet convention (p. 12): a sine whose peak touches
// full scale is 0 dBFS, so RMS is scaled by sqrt(2). A 1 kHz tone at 94 dB SPL
// then reads -26 dBFS (typ., -29 to -23 per Table 1).
static double rms_dbfs(double rms)
{
    return rms <= 0.0 ? -200.0 : 20.0 * log10(rms * M_SQRT2 / FULL);
}

// AC RMS (mean removed), so a DC offset does not hide the noise floor.
static double ac_rms(const slot_stats_t *s)
{
    double m = s->sum / s->n;
    double var = s->sum2 / s->n - m * m;
    return var > 0.0 ? sqrt(var) : 0.0;
}

static bool alive(const slot_stats_t *s)
{
    return s->n > 0 && s->min != s->max;
}

static const char *verdict(const slot_stats_t *l, const slot_stats_t *r)
{
    bool la = alive(l), ra = alive(r);
    if (!la && !ra) {
        if (l->min == 0 && r->min == 0) return "NO DATA: both slots are 0 (SD, VDD, GND, SCK/WS)";
        if (l->min == -1 && r->min == -1) return "SD STUCK HIGH (all bits 1)";
        return "NO DATA: constant value";
    }
    if (!la && ra) return "MIC IN RIGHT SLOT: L/R is not on GND";
    if (l->lsb_nonzero > l->n / 100) return "LOW BYTE NOT 0: bit alignment wrong";
    if (ra) return "BOTH SLOTS ACTIVE: check WS/SCK and L/R";
    if (l->peak >= (int64_t)(FULL * 0.99)) return "OK, CLIPPING";
    return "OK";
}

static void bar(char *out, size_t len, double db)
{
    // -100 dBFS .. 0 dBFS in 2.5 dB steps
    int n = (int)((db + 100.0) / 2.5);
    if (n < 0) n = 0;
    if (n > (int)len - 1) n = (int)len - 1;
    memset(out, '#', n);
    out[n] = '\0';
}

static esp_err_t mic_init(void)
{
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    chan_cfg.dma_desc_num = 8;
    chan_cfg.dma_frame_num = 512;
    ESP_ERROR_CHECK(i2s_new_channel(&chan_cfg, NULL, &s_rx));

    i2s_std_config_t std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(FS),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = CONFIG_MICTEST_I2S_BCLK,
            .ws = CONFIG_MICTEST_I2S_WS,
            .dout = I2S_GPIO_UNUSED,
            .din = CONFIG_MICTEST_I2S_DIN,
        },
    };
    ESP_ERROR_CHECK(i2s_channel_init_std_mode(s_rx, &std_cfg));
#if CONFIG_MICTEST_SD_PULLDOWN
    gpio_pullup_dis(CONFIG_MICTEST_I2S_DIN);
    gpio_pulldown_en(CONFIG_MICTEST_I2S_DIN);
#endif
    ESP_ERROR_CHECK(i2s_channel_enable(s_rx));
    return ESP_OK;
}

// Reads n stereo frames into s_buf, returns frames read.
static size_t read_frames(size_t n)
{
    size_t got = 0;
    ESP_ERROR_CHECK(i2s_channel_read(s_rx, s_buf, n * 2 * sizeof(int32_t), &got, portMAX_DELAY));
    return got / (2 * sizeof(int32_t));
}

#if CONFIG_MICTEST_WAV_SECONDS > 0

// Standard CRC-32 (IEEE 802.3, same as Python zlib.crc32).
static uint32_t crc32_update(uint32_t crc, const uint8_t *p, size_t n)
{
    crc = ~crc;
    while (n--) {
        crc ^= *p++;
        for (int k = 0; k < 8; k++) crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
    }
    return ~crc;
}

static void put_le(uint8_t *p, uint32_t v, int bytes)
{
    for (int i = 0; i < bytes; i++) p[i] = (uint8_t)(v >> (8 * i));
}

static void b64_line(const uint8_t *p, size_t n)
{
    static const char t[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    char out[4 * 48 / 3 + 1];
    size_t o = 0;
    for (size_t i = 0; i < n; i += 3) {
        uint32_t v = p[i] << 16;
        if (i + 1 < n) v |= p[i + 1] << 8;
        if (i + 2 < n) v |= p[i + 2];
        out[o++] = t[(v >> 18) & 63];
        out[o++] = t[(v >> 12) & 63];
        out[o++] = i + 1 < n ? t[(v >> 6) & 63] : '=';
        out[o++] = i + 2 < n ? t[v & 63] : '=';
    }
    out[o] = '\0';
    printf("%s\n", out);
}

static void record_wav(void)
{
    const size_t frames = (size_t)FS * CONFIG_MICTEST_WAV_SECONDS;
    const size_t data_bytes = frames * 2;
    const size_t total = 44 + data_bytes;
    uint8_t *wav = malloc(total);
    if (!wav) {
        ESP_LOGE(TAG, "WAV: not enough RAM for %u bytes", (unsigned)total);
        return;
    }

    // 44-byte PCM header: mono, 16-bit, FS Hz.
    memcpy(wav, "RIFF", 4);
    put_le(wav + 4, total - 8, 4);
    memcpy(wav + 8, "WAVEfmt ", 8);
    put_le(wav + 16, 16, 4);
    put_le(wav + 20, 1, 2);          // PCM
    put_le(wav + 22, 1, 2);          // mono
    put_le(wav + 24, FS, 4);
    put_le(wav + 28, FS * 2, 4);     // byte rate
    put_le(wav + 32, 2, 2);          // block align
    put_le(wav + 34, 16, 2);         // bits per sample
    memcpy(wav + 36, "data", 4);
    put_le(wav + 40, data_bytes, 4);

    ESP_LOGI(TAG, "WAV: recording %d s from the left slot ...", CONFIG_MICTEST_WAV_SECONDS);
    int16_t *pcm = (int16_t *)(wav + 44);   // offset 44 is 2-byte aligned
    size_t done = 0;
    while (done < frames) {
        size_t want = frames - done < CHUNK ? frames - done : CHUNK;
        size_t k = read_frames(want);
        // Top 16 of the 24 valid bits; no gain, so the WAV shows the raw level.
        for (size_t i = 0; i < k; i++) pcm[done + i] = (int16_t)(s_buf[2 * i] >> 16);
        done += k;
    }

    uint32_t crc = crc32_update(0, wav, total);
    ESP_LOGI(TAG, "WAV: sending %u bytes as base64", (unsigned)total);
    printf("WAV_BEGIN %u %08" PRIx32 "\n", (unsigned)total, crc);
    for (size_t i = 0; i < total; i += 48) b64_line(wav + i, total - i < 48 ? total - i : 48);
    printf("WAV_END\n");
    fflush(stdout);
    free(wav);
    ESP_LOGI(TAG, "WAV: done");
}

static bool wav_requested(void)
{
    uint8_t c;
    bool req = false;
    while (uart_read_bytes(CONSOLE, &c, 1, 0) == 1)
        if (c == 'w' || c == 'W') req = true;
    return req;
}

#endif  // CONFIG_MICTEST_WAV_SECONDS > 0

void app_main(void)
{
    ESP_LOGI(TAG, "INMP441 test: SCK=GPIO%d WS=GPIO%d SD=GPIO%d, %d Hz, 32-bit stereo slots, pull-down %s",
             CONFIG_MICTEST_I2S_BCLK, CONFIG_MICTEST_I2S_WS, CONFIG_MICTEST_I2S_DIN, FS,
             CONFIG_MICTEST_SD_PULLDOWN ? "on" : "off");
    ESP_ERROR_CHECK(mic_init());

#if CONFIG_MICTEST_WAV_SECONDS > 0
    ESP_ERROR_CHECK(uart_driver_install(CONSOLE, 256, 0, 0, NULL, 0));
    ESP_LOGI(TAG, "Send 'w' to record a %d s WAV (tools/capture_wav.py).", CONFIG_MICTEST_WAV_SECONDS);
#endif

    // Drop the start-up period with a 2x margin, and measure how long the left
    // slot really stays at zero (a check of the datasheet figure on this board).
    uint32_t first_nonzero = 0;
    for (uint32_t seen = 0; seen < 2 * STARTUP_FRAMES;) {
        size_t k = read_frames(CHUNK);
        for (size_t i = 0; i < k && !first_nonzero; i++)
            if (s_buf[2 * i] != 0) first_nonzero = seen + i + 1;
        seen += k;
    }
    if (first_nonzero)
        ESP_LOGI(TAG, "Start-up: first non-zero left sample at frame %" PRIu32
                 " (%.0f ms; datasheet: zero for %d frames = %.0f ms)",
                 first_nonzero, 1000.0 * first_nonzero / FS, STARTUP_FRAMES, 1000.0 * STARTUP_FRAMES / FS);
    else
        ESP_LOGW(TAG, "Start-up: left slot still all zero after %d frames", 2 * STARTUP_FRAMES);
    ESP_LOGI(TAG, "Columns: L rms (dBFS, sine peak = full scale), approx. dB SPL (= rms + 120, +-3 dB),"
             " L peak, L dc (fraction of FS), R rms, first raw word, words with low byte != 0, verdict");

    const uint32_t per_report = (uint32_t)((int64_t)FS * CONFIG_MICTEST_REPORT_MS / 1000);
    slot_stats_t l, r;
    for (;;) {
#if CONFIG_MICTEST_WAV_SECONDS > 0
        if (wav_requested()) record_wav();
#endif
        stats_reset(&l);
        stats_reset(&r);
        while (l.n < per_report) {
            size_t want = per_report - l.n < CHUNK ? per_report - l.n : CHUNK;
            size_t k = read_frames(want);
            for (size_t i = 0; i < k; i++) {
                stats_add(&l, s_buf[2 * i]);
                stats_add(&r, s_buf[2 * i + 1]);
            }
        }
        double l_rms = rms_dbfs(ac_rms(&l)), l_peak = peak_dbfs((double)l.peak);
        double r_rms = rms_dbfs(ac_rms(&r));
        char b[41];
        bar(b, sizeof(b), l_rms);
        printf("L rms %6.1f dBFS ~%3.0f dB SPL peak %6.1f dBFS dc %+.5f | R rms %6.1f | raw %08" PRIx32
               " lsb!=0 %" PRIu32 "/%" PRIu32 " | %s | %s\n",
               l_rms, l_rms + 120.0, l_peak, l.sum / l.n / FULL, r_rms, (uint32_t)l.first,
               l.lsb_nonzero, l.n, verdict(&l, &r), b);
    }
}
