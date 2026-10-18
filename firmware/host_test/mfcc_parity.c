// Host-side MFCC parity test: C front end vs. Python features.py.
//   make -C firmware/host_test
// Uses the PCM windows and expected MFCCs that training/export.py wrote
// into generated/selftest_vectors.h.
#include <math.h>
#include <stdio.h>

#include "mfcc.h"
#include "generated/selftest_vectors.h"

#define TOL 1e-2f   // absolute, on MFCC values that range roughly -400..+50

int main(void)
{
    static float pcm[MFCC_WIN_SAMPLES];
    static float out[MFCC_N_FRAMES * MFCC_N_MFCC];
    int failed = 0;

    mfcc_init();
    for (int t = 0; t < SELFTEST_N; t++) {
        for (int i = 0; i < MFCC_WIN_SAMPLES; i++) pcm[i] = selftest_pcm[t][i] / 32768.0f;
        mfcc_compute(pcm, out);
        float max_err = 0.0f;
        for (int i = 0; i < MFCC_N_FRAMES * MFCC_N_MFCC; i++) {
            float e = fabsf(out[i] - selftest_mfcc[t][i]);
            if (e > max_err) max_err = e;
        }
        printf("vector %d: max |C - Python| = %.6f %s\n", t, max_err, max_err <= TOL ? "OK" : "FAIL");
        failed |= max_err > TOL;
    }
    return failed;
}
