# mic_test: stand-alone INMP441 check

A small ESP-IDF project that reads the INMP441 with the same I2S settings as
`firmware/` (I2S0 master, Philips, 32-bit slots, 16 kHz, SCK 4 / WS 5 / SD 6)
but needs no model, Wi-Fi or MQTT. It reads both slots and prints, twice a
second, RMS/peak/DC of the left slot, the right-slot level, the first raw word,
the number of words whose low byte is not zero, and a diagnosis (`OK`, wrong
L/R, no data, bit alignment, clipping). On request it records a 5 s 16-bit WAV
and sends it as base64 with a CRC-32.

```sh
cd mic_test
idf.py set-target esp32s3
idf.py build
idf.py -p COM5 flash monitor          # Ctrl+] to leave
python tools/capture_wav.py COM5 snimak.wav   # monitor closed
```

Wiring, how to read the numbers, typical faults and the pass criteria (with
datasheet page references) are in [UPUTSTVO.md](UPUTSTVO.md) (Serbian).

Checked so far: builds without warnings with ESP-IDF v5.3.2 and v5.5.6; CRC-32, base64
and the diagnosis were checked on the host with synthetic signals. Not yet run
on the board.
