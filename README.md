# LogGuard

Acoustic chainsaw detection for illegal logging in NP Prokletije, Montenegro.
This repository holds the code for **PoC 1**: an ESP32-S3 with an INMP441 MEMS
microphone that runs an INT8 DS-CNN on the device and sends alerts over Wi-Fi
MQTT to a laptop.

| Folder | What it is |
| --- | --- |
| `training/` | DS-CNN training on rfcx/frugalai, INT8 export, firmware header generation |
| `firmware/` | ESP-IDF 5.3 project for the ESP32-S3 (I2S mic, MFCC, TFLite Micro, MQTT) |
| `server/` | Mosquitto broker and a Python receiver that logs alerts to SQLite |

## Fixes from the Phase 5 review (3 Oct 2026)

| Problem in the Phase 5 draft | Where it is fixed |
| --- | --- |
| Firmware alarmed on `output[1]` while the dataset has label 0 = chainsaw | Training maps chainsaw to index 1 on purpose; `export.py` writes `MODEL_CHAINSAW_IDX` into `model_meta.h` and the firmware reads it. A test guards the mapping. |
| Training cut every 3 s clip to its first second | Every clip is split into 1 s windows every 0.5 s (`features.windows`); the firmware listens with the same 1 s / 0.5 s windows. |
| No check that the device computes the same MFCCs as Python | `features.py` is the single source of the front end. It exports the window, mel filterbank and DCT into `mfcc_tables.h`, and `firmware/host_test` compares the C code against Python. |
| INT8 threshold hard-coded | The firmware reads input and output scale and zero point from the model at boot, logs them, and applies the threshold as a probability. |
| `alert_send` over LTE/SMS | Replaced by Wi-Fi + MQTT QoS 1 with PUBACK, retries and a small retry queue. |
| `vTaskDelay(60 s)` cooldown stopped reading the microphone | The device keeps listening during the cooldown and only holds back alerts. |

## Quick start

### 1. Train and export the model

```sh
cd training
pip install -r requirements.txt
python train.py --out runs/ds_cnn          # downloads rfcx/frugalai from Hugging Face
python export.py --run runs/ds_cnn         # INT8, checks, writes firmware/main/generated/
python -m pytest -q                        # unit tests + a small synthetic train/export
```

`export.py` stops with an error if the INT8 window F1 drops more than 3 points
against float, if the model is over 40 KB, or if the model uses an op the
firmware does not register. To try the pipeline without downloading the dataset,
use `python train.py --out runs/smoke --synthetic`. Synthetic data only checks
the plumbing; never flash a model trained on it for a real test.

### 2. Check MFCC parity on the laptop

```sh
make -C firmware/host_test     # C front end vs. Python on the self-test vectors
```

### 3. Build and flash

```sh
cd firmware
idf.py set-target esp32s3
idf.py menuconfig              # LogGuard -> Wi-Fi SSID/password, MQTT URI and password
idf.py -p /dev/ttyACM0 flash monitor
```

At boot the device runs **T1**: it compares its MFCCs and model output with
the values Python computed for the same audio, and logs `T1 self-test: PASS`
or `FAIL`. After that it logs one line per window (`p=0.03 raw=... consec=0`).

### 4. Run the server

```sh
cd server
mosquitto_passwd -c mosquitto/passwd logguard     # choose the password set in menuconfig
docker compose up -d                              # or run mosquitto -c mosquitto/mosquitto.conf
pip install -r requirements.txt
python receiver.py --password <password>
./test_publish.sh <password>                      # fake alert, before the device exists
```

With a phone hotspot, put the laptop on the hotspot too and set the MQTT URI to
the laptop's address on that network.

## Wiring (INMP441 to ESP32-S3-DevKitC)

| INMP441 | ESP32-S3 |
| --- | --- |
| VDD | 3V3 (never 5 V) |
| GND | GND |
| L/R | GND (left channel) |
| SCK | GPIO 4 |
| WS | GPIO 5 |
| SD | GPIO 6 |

The pins can be changed in menuconfig under **LogGuard → INMP441 pins**.

## PoC 1 tests

| Test | How this code supports it |
| --- | --- |
| T1 parity | Self-test at boot and `firmware/host_test` |
| T2 detection at 1 m (pass: over 90%) | Per-window log; set **Digital microphone gain** so levels match the training data |
| T3 detection at 200 m (pass: over 80%) | Same; the receiver logs every alert with score and RSSI |
| T4 power (pass: about 0.3 W or less) | **Turn Wi-Fi on only to send** keeps the radio off while listening; turn off **Log the score of every window** to cut UART traffic |

## What has been checked so far

- Python unit tests and a synthetic train/export run pass.
- The C MFCC matches Python to within 1e-5 on the self-test vectors.
- The firmware builds with ESP-IDF v5.3.2 and esp-tflite-micro 1.3.4.
- T1 passes in the ESP32-S3 emulator (QEMU) with the reference kernels. The
  emulator cannot run the ESP-NN SIMD kernels, so the real board still has to
  confirm T1 and the timing.
- The receiver stored a test alert from a local Mosquitto with password login.

Not yet done: training on the real rfcx/frugalai data, and any test on hardware.
