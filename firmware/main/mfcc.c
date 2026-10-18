#include "mfcc.h"

#include <math.h>

#define PI_F 3.14159265358979323846f

static float s_cos[MFCC_N_FFT / 2];
static float s_sin[MFCC_N_FFT / 2];
static int s_bitrev[MFCC_N_FFT];
static float s_re[MFCC_N_FFT];
static float s_im[MFCC_N_FFT];

void mfcc_init(void)
{
    for (int k = 0; k < MFCC_N_FFT / 2; k++) {
        s_cos[k] = cosf(2.0f * PI_F * k / MFCC_N_FFT);
        s_sin[k] = -sinf(2.0f * PI_F * k / MFCC_N_FFT);
    }
    int bits = 0;
    while ((1 << bits) < MFCC_N_FFT) bits++;
    for (int i = 0; i < MFCC_N_FFT; i++) {
        int r = 0;
        for (int b = 0; b < bits; b++) r |= ((i >> b) & 1) << (bits - 1 - b);
        s_bitrev[i] = r;
    }
}

// In-place iterative radix-2 FFT on s_re/s_im.
static void fft(void)
{
    for (int i = 0; i < MFCC_N_FFT; i++) {
        int j = s_bitrev[i];
        if (j > i) {
            float t = s_re[i]; s_re[i] = s_re[j]; s_re[j] = t;
            t = s_im[i]; s_im[i] = s_im[j]; s_im[j] = t;
        }
    }
    for (int len = 2; len <= MFCC_N_FFT; len <<= 1) {
        int step = MFCC_N_FFT / len;
        for (int i = 0; i < MFCC_N_FFT; i += len) {
            for (int k = 0; k < len / 2; k++) {
                float wr = s_cos[k * step], wi = s_sin[k * step];
                int a = i + k, b = i + k + len / 2;
                float tr = s_re[b] * wr - s_im[b] * wi;
                float ti = s_re[b] * wi + s_im[b] * wr;
                s_re[b] = s_re[a] - tr; s_im[b] = s_im[a] - ti;
                s_re[a] += tr;          s_im[a] += ti;
            }
        }
    }
}

void mfcc_compute(const float *pcm, float *out)
{
    float power[MFCC_N_BINS];
    float logmel[MFCC_N_MELS];

    for (int f = 0; f < MFCC_N_FRAMES; f++) {
        const float *x = pcm + f * MFCC_HOP;
        for (int i = 0; i < MFCC_N_FFT; i++) {
            s_re[i] = x[i] * mfcc_window[i];
            s_im[i] = 0.0f;
        }
        fft();
        for (int k = 0; k < MFCC_N_BINS; k++) {
            power[k] = s_re[k] * s_re[k] + s_im[k] * s_im[k];
        }

        const float *w = mfcc_mel_weights;
        for (int m = 0; m < MFCC_N_MELS; m++) {
            float acc = 0.0f;
            for (int j = 0; j < mfcc_mel_len[m]; j++) {
                acc += power[mfcc_mel_start[m] + j] * w[j];
            }
            w += mfcc_mel_len[m];
            logmel[m] = logf(acc + MFCC_LOG_EPS);
        }

        float *o = out + f * MFCC_N_MFCC;
        for (int c = 0; c < MFCC_N_MFCC; c++) {
            const float *d = mfcc_dct + c * MFCC_N_MELS;
            float acc = 0.0f;
            for (int m = 0; m < MFCC_N_MELS; m++) acc += d[m] * logmel[m];
            o[c] = acc;
        }
    }
}
