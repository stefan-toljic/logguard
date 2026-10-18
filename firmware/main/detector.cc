#include "detector.h"

#include <math.h>

#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"

#include "generated/model_data.h"
#include "generated/model_meta.h"
#include "generated/selftest_vectors.h"
#include "mfcc.h"

static const char *TAG = "detector";

// The DS-CNN uses ~56 KB with ESP-NN kernels; the log at boot prints the real figure.
constexpr int kArenaSize = 80 * 1024;
alignas(16) static uint8_t s_arena[kArenaSize];
static float s_feats[MFCC_N_FRAMES * MFCC_N_MFCC];
static tflite::MicroInterpreter *s_interp;
static TfLiteTensor *s_in;
static TfLiteTensor *s_out;

esp_err_t detector_init(void)
{
    mfcc_init();

    const tflite::Model *model = tflite::GetModel(g_model_data);
    if (model->version() != TFLITE_SCHEMA_VERSION) {
        ESP_LOGE(TAG, "model schema %lu != %d", model->version(), TFLITE_SCHEMA_VERSION);
        return ESP_FAIL;
    }
    // Keep in sync with FIRMWARE_OPS in training/export.py.
    static tflite::MicroMutableOpResolver<9> resolver;
    resolver.AddConv2D();
    resolver.AddDepthwiseConv2D();
    resolver.AddFullyConnected();
    resolver.AddSoftmax();
    resolver.AddMean();
    resolver.AddReshape();
    resolver.AddAveragePool2D();
    resolver.AddQuantize();
    resolver.AddDequantize();

    static tflite::MicroInterpreter interp(model, resolver, s_arena, kArenaSize);
    if (interp.AllocateTensors() != kTfLiteOk) {
        ESP_LOGE(TAG, "AllocateTensors failed (arena %d bytes)", kArenaSize);
        return ESP_FAIL;
    }
    s_interp = &interp;
    s_in = interp.input(0);
    s_out = interp.output(0);
    if (s_in->type != kTfLiteInt8 || s_out->type != kTfLiteInt8 ||
        s_in->bytes != sizeof(s_feats) / sizeof(float)) {
        ESP_LOGE(TAG, "unexpected model I/O: in type %d bytes %u, out type %d",
                 s_in->type, (unsigned)s_in->bytes, s_out->type);
        return ESP_FAIL;
    }
    // Scales are read from the model, never hard-coded.
    ESP_LOGI(TAG, "model %u B, arena used %u B, in scale %.6f zp %ld, out scale %.6f zp %ld, chainsaw idx %d",
             g_model_data_len, (unsigned)interp.arena_used_bytes(),
             s_in->params.scale, (long)s_in->params.zero_point,
             s_out->params.scale, (long)s_out->params.zero_point, MODEL_CHAINSAW_IDX);
    return ESP_OK;
}

// Normalize with the training mean/std, then quantize with the model's input scale.
static void quantize_features(const float *feats)
{
    const float scale = s_in->params.scale;
    const int zp = s_in->params.zero_point;
    int8_t *dst = s_in->data.int8;
    for (int f = 0; f < MFCC_N_FRAMES; f++) {
        for (int c = 0; c < MFCC_N_MFCC; c++) {
            int i = f * MFCC_N_MFCC + c;
            float v = (feats[i] - model_feat_mean[c]) / model_feat_std[c];
            int q = (int)lroundf(v / scale) + zp;
            dst[i] = (int8_t)(q > 127 ? 127 : (q < -128 ? -128 : q));
        }
    }
}

static esp_err_t invoke(detection_t *out)
{
    int64_t t0 = esp_timer_get_time();
    if (s_interp->Invoke() != kTfLiteOk) return ESP_FAIL;
    out->invoke_us = (uint32_t)(esp_timer_get_time() - t0);
    for (int k = 0; k < MODEL_N_CLASSES; k++) out->raw[k] = s_out->data.int8[k];
    out->chainsaw_raw = out->raw[MODEL_CHAINSAW_IDX];
    out->chainsaw_prob = (out->chainsaw_raw - s_out->params.zero_point) * s_out->params.scale;
    return ESP_OK;
}

esp_err_t detector_run(const float *pcm, detection_t *out)
{
    int64_t t0 = esp_timer_get_time();
    mfcc_compute(pcm, s_feats);
    out->mfcc_us = (uint32_t)(esp_timer_get_time() - t0);
    quantize_features(s_feats);
    return invoke(out);
}

bool detector_selftest(void)
{
    float *pcm = (float *)heap_caps_malloc(MFCC_WIN_SAMPLES * sizeof(float), MALLOC_CAP_SPIRAM);
    if (!pcm) return false;
    bool pass = true;
    for (int t = 0; t < SELFTEST_N; t++) {
        for (int i = 0; i < MFCC_WIN_SAMPLES; i++) pcm[i] = selftest_pcm[t][i] / 32768.0f;
        detection_t d = {};
        if (detector_run(pcm, &d) != ESP_OK) {
            pass = false;
            break;
        }

        float mfcc_err = 0.0f;
        for (int i = 0; i < MFCC_N_FRAMES * MFCC_N_MFCC; i++) {
            mfcc_err = fmaxf(mfcc_err, fabsf(s_feats[i] - selftest_mfcc[t][i]));
        }
        // ESP-NN kernels may round differently from the reference kernels by one step.
        int out_err = 0;
        for (int k = 0; k < MODEL_N_CLASSES; k++) {
            int e = abs(d.raw[k] - selftest_out[t][k]);
            if (e > out_err) out_err = e;
        }
        bool ok = mfcc_err <= 1e-2f && out_err <= 1;
        pass &= ok;
        ESP_LOGI(TAG, "T1 vector %d: mfcc max err %.5f, output %d/%d vs python %d/%d, "
                 "mfcc %lu us, invoke %lu us: %s",
                 t, mfcc_err, d.raw[0], d.raw[1], selftest_out[t][0], selftest_out[t][1],
                 (unsigned long)d.mfcc_us, (unsigned long)d.invoke_us, ok ? "PASS" : "FAIL");
    }
    heap_caps_free(pcm);
    return pass;
}
